# Attack evidence — 8 attacks, 8 refusals

Run against the live vault on QDay Aevum Testnet, using the **agent key** (the untrusted one) as the attacker. Each attempt is simulated with `eth_call`, so the reason printed below is the contract's own revert — not a claim about what would happen.

Reproduce:

```bash
set -a && . ./.env && set +a
python agent/attack_sim.py
```

## Result

| # | Attack (as the agent) | Expected | Contract answered |
| --- | --- | --- | --- |
| 1 | Pay invoice #6 to a payee that is not allowlisted | `PayeeNotAllowed` | **`PayeeNotAllowed`** |
| 2 | Pay invoice #2 (0.50) over the 0.30 per-tx cap | `CapExceeded` | **`CapExceeded`** |
| 3 | Replay invoice #1, already paid | `AlreadyPaid` | **`AlreadyPaid`** |
| 4 | Call `setMandate` to raise its own limits | `OwnableUnauthorizedAccount` | **`OwnableUnauthorizedAccount`** |
| 5 | Call `pause` on the vault | `OwnableUnauthorizedAccount` | **`OwnableUnauthorizedAccount`** |
| 6 | Call `withdraw` to take the balance | `OwnableUnauthorizedAccount` | **`OwnableUnauthorizedAccount`** |
| 7 | Call `setPayeeAllowed` to whitelist an attacker address | `OwnableUnauthorizedAccount` | **`OwnableUnauthorizedAccount`** |
| 8 | Submit an approval signed by a key that is not the owner | `BadApproval` | **`BadApproval`** |

```
8/8 attacks refused for the expected reason
```

## What each refusal proves

- **#1** — a prompt injection that redirects the payee dies at the allowlist. The agent cannot add a payee (#7).
- **#2** — a hallucinated amount dies at the per-tx cap. The agent cannot raise the cap (#4).
- **#3** — a retry loop or a replay dies at the registry's `paid` flag, flipped inside the same transaction.
- **#4–#7** — the agent key is not the owner key. Every authority function reverts with OpenZeppelin's `OwnableUnauthorizedAccount`, including the pause switch it might want to undo.
- **#8** — an approval is bound to `(invoiceId, amount, payee, nonce, deadline)` via EIP-712; a signature from any other key fails to recover to the owner.

## Note on #8

The first run of this script reported `DailyCapExceeded` instead of `BadApproval` for #8 — the daily budget (0.70 spent of 0.80) was exhausted before the approval check was reached. That is the correct order of checks, and it is worth stating plainly: the attack was blocked *earlier* than the test expected. To exercise the approval branch specifically, the owner temporarily raised the daily cap to 1.00, re-ran the script, and restored it to 0.80 afterwards. Both transactions are on chain:

- daily cap → 1.00: `0x87841002a82a7d2acaeaa19f860d4ca2a4bc302060650f5f3e64034a3fafd86f`
- daily cap → 0.80: `0xccf8cc75a919510b97e9875826c528dd69935bbbfae7e7f97f62db79e7e5a30f`

## What is *not* covered

These attacks assume the agent key is compromised, not the owner key. An attacker holding the owner key can rewrite the mandate, unpause and withdraw — that is why the roadmap puts the owner behind a multisig before mainnet. See `docs/THREAT-MODEL.md`.
