# Security review — Slither + manual pass

Two layers: an automated pass with Slither, then a manual read against the classes that matter for a payment vault. The point of publishing this is that the findings are visible, not that the tool printed zero.

```
slither . --compile-force-framework foundry --filter-paths "lib/|test/" --exclude-dependencies
→ analyzed 33 contracts with 102 detectors, 7 result(s) found
```

**No high or medium severity findings.** All seven are informational, listed below with the decision taken on each.

## Automated findings

| # | Detector | Location | Decision |
| --- | --- | --- | --- |
| 1 | `unused-return` | `PolicyVault._checkApproval` — third return of `ECDSA.tryRecover` discarded | **Accepted.** The third value is the recovered address on failure; `tryRecover`'s `RecoverError` is checked on the next line, which is the actual guard. |
| 2 | `missing-zero-check` | `PaymentReceipt.constructor(vault_)` | **Accepted.** Only the vault deploys this contract (`new PaymentReceipt(address(this))`), so a zero address is unreachable. Adding a check would force a redeploy for no behavioural change. |
| 3–6 | `timestamp` (×4) | `validUntil`, `dueAt`, `deadline`, `_rollWindow`, `remainingToday` | **Accepted, by design.** Time is the mechanism: session expiry, invoice deadlines, approval deadlines and the 24h budget window. Validator drift of a few seconds moves a payment to the next block, not into a different decision. No value depends on exact timestamp equality. |
| 7 | `cyclomatic-complexity` | `PolicyVault._pay` (12) | **Accepted.** The complexity *is* the product: ten ordered policy checks, each with a distinct custom error so the agent can log a precise refusal reason. Splitting it into helpers would hide the order that the tests assert. |

## Manual pass — the classes that actually apply

| Class | Where it could bite | What the code does |
| --- | --- | --- |
| **Reentrancy** | `pay` → `token.transfer` → a malicious token calls back | `nonReentrant` on both entrypoints; state (`daySpent`, `markPaid`) is written **before** the transfer; the vault only calls a token it was constructed with. |
| **Access control** | agent raising its limits, unpausing, withdrawing | `onlyOwner` on every setter; the agent key is a different key, tested per selector (`test_agentCannotSetMandate/Pause/Withdraw/AllowPayee`). |
| **Signature replay** | reusing an approval | EIP-712 binds `(invoiceId, amount, payee, nonce, deadline)`; `nonce` increments on use; the invoice is marked paid in the same transaction. |
| **Signature malleability** | high-`s` variant of a valid signature | OpenZeppelin `ECDSA.tryRecover` rejects `s > secp256k1n/2`. |
| **Cross-chain replay** | same signature on another chain | The EIP-712 domain includes `chainId` and `verifyingContract`. |
| **Integer issues** | overflow on `daySpent + amount` | Solidity 0.8 checked arithmetic; `uint96` caps amounts at ~7.9e28 base units (7.9e22 tUSD8), far above any real invoice. |
| **Denial of service** | an invoice that always reverts blocks the loop | Payments are per-invoice; a reverting invoice is skipped by the agent, not fatal to the batch. |
| **Front-running** | someone races a payment | Harmless: the invoice pays once; a race produces `AlreadyPaid` for the loser. |
| **Griefing via allowlist** | payee contract that reverts on receive | `tUSD8.transfer` to a reverting payee reverts the whole call; funds stay in the vault. The owner can delist the payee. |
| **Token assumptions** | fee-on-transfer or rebasing token | The vault assumes a plain ERC-20; a fee-on-transfer token would leave the vault accounting short by the fee. Documented as a deployment requirement: settlement token must be a standard ERC-20. |

## Not covered here

- **No formal verification** and no third-party audit. This is a testnet build; `docs/ARCHITECTURE.md` puts an audit before any mainnet deployment.
- **Owner key compromise** is out of scope by design — see `docs/THREAT-MODEL.md`.
- **The agent process itself** (Python) is not audited; it holds no authority, so a full compromise still lands inside the mandate.

## What would be done before mainnet

1. External audit of the two contracts.
2. Owner behind a Safe multisig; agent as an ERC-4337 session key.
3. Settlement token pinned to a known-good stablecoin with a documented no-fee-on-transfer guarantee.
4. Invariant fuzzing (Foundry invariant handlers) over multi-agent, multi-day sequences.
