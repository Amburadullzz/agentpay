# AgentPay — contract specification (design only, no code until Nov 16)

Chain: Aevum Testnet 44005 · settlement token: tUSD8 `0x456569838f1d43009A91ebA4263147Afd7233483` (ERC-20, **6 decimals**).
Solidity 0.8.24, Foundry. All amounts are raw tUSD8 units (1 tUSD8 = 1e6).

## Roles

| Role | Key | Can do |
| --- | --- | --- |
| Owner (human) | approver wallet `0xEb20…5B6b` | set mandates, fund/withdraw vault, pause, approve above-threshold invoices |
| Agent | agent wallet `0x4668…aF89` | call `pay()` / `payWithApproval()` only |
| Provider | any address | create invoices, receive settlement |

The agent key never holds owner rights. A compromised agent can at most spend inside the mandate.

## 1. InvoiceRegistry

```solidity
struct Invoice {
    address issuer;     // who created it
    address payee;      // who gets paid (may equal issuer)
    uint96  amount;     // tUSD8 units
    bytes32 memoHash;   // keccak256 of human-readable memo
    uint64  dueAt;      // unix seconds; 0 = no deadline
    bool    paid;
    bool    cancelled;
}
```

```solidity
function createInvoice(address payee, uint96 amount, bytes32 memoHash, uint64 dueAt)
    external returns (uint256 id);
function cancelInvoice(uint256 id) external;              // issuer only, unpaid only
function markPaid(uint256 id, address payer) external;     // vault only (role-gated)
function getInvoice(uint256 id) external view returns (Invoice memory);
function invoiceCount() external view returns (uint256);
```

Events: `InvoiceCreated(id, issuer, payee, amount, dueAt)`, `InvoiceCancelled(id)`, `InvoicePaid(id, payer, amount)`.

Errors: `NotIssuer()`, `AlreadyPaid()`, `AlreadyCancelled()`, `UnknownInvoice()`, `ZeroAmount()`, `NotVault()`.

Invariants
- `paid` and `cancelled` are mutually exclusive and one-way.
- Only the vault address can flip `paid`.
- `id` is sequential from 1 and never reused.

## 2. PolicyVault

```solidity
struct Mandate {
    bool    active;
    uint96  perTxCap;          // max single payment
    uint96  dailyCap;          // max rolling 24h spend
    uint96  approvalThreshold; // >= this amount needs an owner signature
    uint64  validUntil;        // session expiry — 0 = no expiry
    uint64  dayStart;          // start of current 24h window
    uint96  daySpent;          // spent in current window
    uint32  nonce;             // per-agent approval nonce
}
```

The mandate is a **scoped session**, not a permanent grant: an owner hands an agent a budget, a payee set and an expiry, and the authority dies on its own. Expiry is checked on every payment, so a forgotten agent cannot keep spending after the job is done.

```solidity
function setMandate(address agent, uint96 perTxCap, uint96 dailyCap, uint96 approvalThreshold, uint64 validUntil) external; // owner
function setPayeeAllowed(address payee, bool allowed) external;                                          // owner
function deposit(uint96 amount) external;                                                                // owner (tUSD8 transferFrom)
function withdraw(uint96 amount) external;                                                               // owner, only while paused
function pause() external;                                                                               // owner
function unpause() external;                                                                             // owner
function revokeSession(address agent) external;                                                          // owner: active = false, immediate
function pay(uint256 invoiceId) external;                                                                // agent
function payWithApproval(uint256 invoiceId, uint256 deadline, bytes calldata sig) external;              // agent + owner sig
function mandateOf(address agent) external view returns (Mandate memory);
function isPayeeAllowed(address payee) external view returns (bool);
function paused() external view returns (bool);
```

Events: `MandateSet(agent, perTxCap, dailyCap, approvalThreshold)`, `PayeeAllowed(payee, allowed)`, `Deposited(from, amount)`, `Withdrawn(to, amount)`, `Paid(invoiceId, agent, payee, amount)`, `ApprovalUsed(invoiceId, nonce)`, `PausedBy(who)`, `UnpausedBy(who)`.

Errors: `VaultPaused()`, `NotOwner()`, `NotAgent()`, `SessionExpired()`, `PayeeNotAllowed()`, `CapExceeded()`, `DailyCapExceeded()`, `ApprovalRequired()`, `BadApproval()`, `ApprovalExpired()`, `InvoiceExpired()`, `AlreadyPaid()`, `InsufficientVaultBalance()`.

`pay()` check order (cheap → expensive, and every branch has a distinct error so the agent can log a precise reason):

1. `paused` → `VaultPaused`
2. caller has an active mandate → `NotAgent`
3. `validUntil == 0 || block.timestamp <= validUntil` → `SessionExpired`
4. invoice exists, unpaid, not cancelled → `UnknownInvoice` / `AlreadyPaid`
5. `block.timestamp <= dueAt || dueAt == 0` → `InvoiceExpired`
6. `isPayeeAllowed[invoice.payee]` → `PayeeNotAllowed`
7. `amount <= perTxCap` → `CapExceeded`
8. roll the 24h window if `block.timestamp >= dayStart + 86400`
9. `daySpent + amount <= dailyCap` → `DailyCapExceeded`
10. `amount < approvalThreshold` → otherwise `ApprovalRequired` (must use `payWithApproval`)
11. effects: `daySpent += amount`, `registry.markPaid(id, agent)`
12. interaction: `tUSD8.transfer(payee, amount)` → `InsufficientVaultBalance` / revert

Approval signature (EIP-712):

```
domain: { name: "AgentPay", version: "1", chainId: 44005, verifyingContract: <vault> }
type:   Approval(uint256 invoiceId, uint256 amount, address payee, uint256 nonce, uint256 deadline)
```

`payWithApproval` verifies the signature against the owner, checks `nonce == mandate.nonce` (then increments), `deadline >= block.timestamp`, and re-derives `amount`/`payee` from the invoice — the signature can never authorize a different amount than the invoice carries.

Invariants (property-tested)
- Vault balance only decreases via `pay`/`payWithApproval`/`withdraw`.
- `withdraw` reverts while not paused.
- `daySpent` never exceeds `dailyCap` within a window.
- An invoice is paid at most once, across both entrypoints.
- Agent cannot call any owner function (explicitly tested per selector).
- Pausing blocks `pay` and `payWithApproval` immediately, even for an already-signed approval.

## 3. Receipts (core, not stretch)

The rubric asks for **verifiable receipts**, so a paid invoice mints proof rather than only emitting an event.

```solidity
function mintReceipt(uint256 invoiceId) external returns (uint256 tokenId); // vault only, after payment
function receiptOf(uint256 invoiceId) external view returns (uint256);
```

A minimal ERC-721 where `tokenId == invoiceId`, minted to the payer and carrying the payee, amount and timestamp in the token metadata (on-chain, no IPFS dependency). Anyone can verify a payment by opening the token; the issuer can show a receipt without trusting either party's database.

## 4. Stretch (only if the core is done by Dec 1)

- Batch payroll: `payBatch(uint256[] ids)` with the same per-invoice checks and a single daily-cap accounting pass.
- ERC-4337 session key: wrap the mandate as a session-key validator so the agent's key is a scoped signer on a smart account instead of a plain EOA. Big platform-integration points, but only after the vault is proven.
