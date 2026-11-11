# AgentPay — architecture

This document explains the design decisions behind AgentPay: what each component owns, how a payment actually flows, where the trust boundaries are, and what happens when something goes wrong.

## 1. Design premise

An AI agent that can spend money needs three things it cannot get from a prompt:

1. **A hard ceiling** it cannot raise — enforced by something that does not run in the agent's context.
2. **A narrow destination set** it cannot widen — so a prompt injection cannot redirect funds.
3. **A human override** that works even when the agent is wrong, compromised, or looping.

AgentPay puts all three on-chain, in a contract the agent calls but does not control. The agent becomes a *proposer*: it decides what to pay, never how much authority it has.

## 2. Components

### InvoiceRegistry (on-chain)

The source of truth for "what is owed". A provider writes an invoice; the record is immutable except for two one-way transitions: `paid` and `cancelled`.

- Sequential ids, so an invoice reference is short and unambiguous.
- `memoHash` keeps the human-readable description off-chain while still binding it: the agent hashes the memo it was given and compares. A memo that does not match means the invoice was tampered with between issuance and payment.
- `markPaid` is gated to the vault address. The registry does not trust the agent to report its own success — only the component that moved the money can close an invoice.

### PolicyVault (on-chain)

The only component holding funds. It answers one question per call: *is this payment inside the mandate?* Every check is a `require` with its own custom error, because the agent logs the error name as the refusal reason — a precise reason is worth more than a generic revert.

State per agent: caps, current 24h window, spend in that window, approval nonce. State per payee: allowed flag. Global: paused flag, owner.

The vault never calls back into the agent, so there is no reentrancy surface from the agent side. The only external call is `tUSD8.transfer`, which happens **after** all state updates (checks-effects-interactions).

### Agent (off-chain)

A loop with three responsibilities:

1. **Read** — pull open invoices and the mandate.
2. **Decide** — compare amount, payee, due date and memo hash against the mandate; classify as `PAY`, `ASK_APPROVAL`, or `REFUSE`.
3. **Act** — simulate the call (`eth_call`) first; only send if the simulation succeeds. A simulation failure means the on-chain rules already rejected it, so sending would only burn gas.

The agent holds a key with **no owner rights**. It cannot set mandates, allow payees, pause, unpause, or withdraw.

### Dashboard (off-chain)

A read-mostly UI over events: invoices, mandate state, pending approvals, the audit trail, and the pause button. The approval signing happens with the **owner** key, which the dashboard does not otherwise hold in the agent's process.

## 3. Payment flow

```
provider                     registry                      agent                    vault                     token
   │                            │                            │                        │                          │
   ├─ createInvoice ───────────►│                            │                        │                          │
   │                            │◄──── read open invoices ───┤                        │                          │
   │                            │◄──── read mandate ─────────┤                        │                          │
   │                            │                            │                        │                          │
   │                            │                     decide: PAY                    │                          │
   │                            ├─────── pay(id) ───────────┼───────────────────────►│                          │
   │                            │                            │                        ├─ checks (10) ─┐          │
   │                            │◄──── markPaid(id, agent) ──┼────────────────────────┤               │          │
   │                            │                            │                        ├─ transfer ────┼─────────►│
   │                            │                            │◄─── Paid event ────────┤               │          │
```

Above the approval threshold the middle step changes: the agent emits an approval request, the owner signs an EIP-712 `Approval(invoiceId, amount, payee, nonce, deadline)`, and the agent submits `payWithApproval`. The signature is bound to the invoice id, so it cannot be replayed against a different invoice, and the nonce makes reuse fail even for the same one.

## 4. Trust boundaries

| Boundary | Trusted for | Not trusted for |
| --- | --- | --- |
| Agent | choosing which invoice to pay | amounts, payees, its own limits |
| Provider | the invoice content it authored | marking invoices paid |
| Owner | configuring the mandate, approving large payments | day-to-day operation |
| Vault | enforcing caps and allowlist | deciding what *should* be paid |
| Registry | recording state | moving funds |

The interesting consequence: **a fully compromised agent still cannot overspend.** The worst it can do inside one day is `dailyCap`, to allowlisted payees only, once per invoice. That is the property the whole design exists to create, and the one the test suite proves.

## 5. Failure modes and responses

| Failure | What happens | Why it is safe |
| --- | --- | --- |
| Agent hallucinates an amount | `CapExceeded` / `DailyCapExceeded` | caps are on-chain |
| Agent invents a payee | `PayeeNotAllowed` | allowlist is owner-set |
| Agent replays an invoice | `AlreadyPaid` | registry flips `paid` in the same tx |
| Agent reuses an approval | `BadApproval` | nonce increments per approval |
| Agent loops on a small invoice | blocked after the first success | idempotency per invoice |
| Agent key leaks | bounded loss = remaining daily cap | mandate + pause |
| Owner key leaks | full vault, but no agent involvement needed | out of scope; recommend a hardware wallet |
| tUSD8 transfer reverts | whole call reverts, no partial state | checks-effects-interactions |

## 6. Deliberate omissions (and why)

- **No upgradeability.** A proxy adds an admin key that can rewrite the rules — exactly the trust we are trying to remove. Deploy once, immutable.
- **No interest, no yield, no rebalancing.** Out of scope; the vault is a spending account, not a treasury.
- **No off-chain signature for small payments.** The agent's key alone pays under the threshold; requiring a human for every coffee would make the product pointless.
- **No multi-sig in v1.** One owner key. A 2-of-3 owner is a natural v2 and does not change the agent-facing surface.

## 7. Cost profile

At 1 gwei on Aevum:

| Operation | Gas | Cost |
| --- | --- | --- |
| Deploy registry | ~600k | negligible on testnet |
| Deploy vault | ~900k | negligible on testnet |
| `pay` | ~80k | ~0.00008 tQDAY |
| `createInvoice` | ~90k | ~0.00009 tQDAY |

The faucet gives 5 tQDAY per 24h per address, so a full demo (2 deploys + setup + 4 invoices + 4 payments) fits in a single claim with room to spare. Deployments are only repeated when the contract changes materially.

## 8. What the demo must prove

1. A payment inside the mandate succeeds end-to-end with a real tUSD8 transfer.
2. A payment over the per-tx cap is refused by the contract, not by the agent's good manners.
3. A payment above the approval threshold requires a human signature.
4. Replaying either the payment or the approval fails.
5. The pause switch stops the agent immediately.

Each of those maps to a named test in `test/`, and the final README carries that mapping as a table.
