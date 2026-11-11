# AgentPay — test plan

Goal: every safety claim in the demo is proven by a test, and the test names map 1:1 to the judging criteria "safety, trust and controls" (15 pts).

## Unit tests (Foundry)

### PolicyVault — happy paths
- `test_pay_withinCaps_transfersAndMarksPaid` — vault balance −amount, payee +amount, invoice `paid == true`, `Paid` event.
- `test_pay_multipleInvoicesAccumulateDaily` — 3 payments under the cap; `daySpent` equals the sum.
- `test_pay_resetsDailyWindowAfter24h` — warp 86400+1, `daySpent` resets, payment allowed again.
- `test_payWithApproval_aboveThreshold` — signature from owner, invoice paid once, nonce incremented.

### PolicyVault — refusals (each one is a demo beat)
| Test | Expected error |
| --- | --- |
| payee not allowlisted | `PayeeNotAllowed` |
| amount > perTxCap | `CapExceeded` |
| amount pushes daySpent over dailyCap | `DailyCapExceeded` |
| invoice already paid (direct replay) | `AlreadyPaid` |
| second `pay` with same calldata | `AlreadyPaid` |
| amount ≥ threshold via `pay()` | `ApprovalRequired` |
| approval signature from wrong key | `BadApproval` |
| approval reused (same nonce) | `BadApproval` |
| approval past deadline | `ApprovalExpired` |
| invoice past `dueAt` | `InvoiceExpired` |
| vault paused | `VaultPaused` |
| non-agent caller | `NotAgent` |

### Access control
- `test_agent_cannotSetMandate`, `test_agent_cannotPause`, `test_agent_cannotWithdraw`, `test_agent_cannotAllowPayee` — one test per selector, each expects `NotOwner`.
- `test_onlyVaultCanMarkPaid` — direct `registry.markPaid` from a random address → `NotVault`.

### Fuzz / invariant
- `invariant_balanceNeverNegative` — sum of outflows ≤ deposits.
- `invariant_daySpentNeverExceedsCap` — fuzz `pay` amounts and timestamps.
- `invariant_invoicePaidAtMostOnce` — fuzz sequences of `pay` / `payWithApproval` on the same id.
- `testFuzz_capBoundary` — amount exactly `perTxCap` passes, `perTxCap + 1` reverts.

## Integration (against a tUSD8-compatible mock and the live testnet)

- Mock tUSD8 with **6 decimals** (not 18) — this is the bug class most likely to slip in.
- End-to-end: `createInvoice → pay → assert balances` on a local Anvil fork, then the same script on Aevum testnet with real tUSD8.
- One live testnet run recorded to the explorer, linked in the README as "evidence of Aevum integration" (required deliverable #2).

## Gas budget on testnet (faucet is 5 tQDAY / 24h)

| Action | Approx gas | Notes |
| --- | --- | --- |
| Deploy registry | ~600k | once |
| Deploy vault | ~900k | once |
| `setMandate` + `allowPayee` ×3 | ~150k | setup |
| `createInvoice` | ~90k | per invoice |
| `pay` | ~80k | per payment |

A full demo run (2 deploys + setup + 4 invoices + 4 payments) fits inside one 5 tQDAY claim at 1 gwei. Keep a second funded address as backup.

## What "done" looks like

`forge test` green with ≥ 30 tests, `forge coverage` ≥ 90% on both contracts, one recorded testnet run, and a README table mapping each safety feature to its test name. That table is what a judge reads first.
