# DoraHacks submission — copy-paste text

Everything below is ready to paste into the submission form. Only the video URL and the GitHub URL need to be live first.

## Project name

```
AgentPay
```

## Tagline (one line)

```
Policy-bound stablecoin payments for AI agents — the agent proposes, the contract decides.
```

## Track

```
Native AI Assistants
```

## Short description (for the card / listing)

```
An AI agent that can pay invoices without ever being trusted with a wallet. A policy vault on
QDay Aevum enforces per-payment and daily caps, a payee allowlist, one-payment-per-invoice,
an EIP-712 approval threshold, session expiry and a pause switch — so a compromised or
hallucinating agent can only spend inside its mandate. Every settlement mints an on-chain
receipt NFT.
```

## Full description

```
THE PROBLEM

Agents can already decide to buy something. Giving one a funded wallet means trusting it with
unbounded authority: one hallucinated amount or one prompt injection and the money is gone.
A limit written in the prompt is not a limit — it is a suggestion the agent can talk itself out of.

WHAT WE BUILT

AgentPay moves the mandate on-chain, outside the agent.

- A provider issues an invoice on-chain: payee, amount, memo hash, due date.
- An agent reads open invoices, compares them against its mandate, and asks the vault to pay.
- The PolicyVault is the only component holding money and the only one that decides whether a
  payment is inside the mandate: per-transaction cap, rolling 24h cap, payee allowlist, one
  payment per invoice, approval threshold above which a human must sign (EIP-712), session
  expiry, instant revocation, and an owner-only pause switch.
- The agent key holds no owner rights. It cannot raise its own limits, allow a payee, unpause
  the vault, withdraw, or mark an invoice paid.
- Every settlement mints an ERC-721 receipt with on-chain metadata — proof that needs no
  trusted server.

WHAT IS LIVE ON AEVUM TESTNET

- PolicyVault 0x3438513Ca98021c976D07D4584Ea6742eF2E5B22 (deploys its registry and receipt
  contract in the constructor, so one deployment is the whole system)
- InvoiceRegistry 0x8F4Fd4Df4e77DaC2BEdA80Aa7193322D658401C8
- PaymentReceipt 0x4bf8b703715e8BC777e3D51D9B20d4C09c07981a
- Settlement token: tUSD8 (6 decimals) 0x456569838f1d43009A91ebA4263147Afd7233483

The demo was executed end to end on the testnet, not simulated: a payment inside the mandate, a
payment refused for exceeding the per-transaction cap, an approval above the threshold signed
off-chain and submitted by the agent, a replay attempt that reverts, and a kill switch that
blocks the agent immediately. All transactions are linked in docs/EVIDENCE.md.

ENGINEERING

- 3 contracts, Solidity 0.8.24, Foundry
- 57 tests, 100% line coverage on all three contracts, fuzz tests over cap boundaries and
  replay paths, per-selector access-control tests
- Python agent (web3.py) that simulates every call with eth_call before spending gas, retries
  transient RPC failures with backoff, and logs every decision with a precise reason
- Static viem dashboard that reads mandate, invoices, receipts and events straight from chain —
  no backend, no indexer
- Threat model documented: what a compromised agent can and cannot do

WHY IT MATTERS

The blast radius of a compromised agent is the mandate, not the balance. That is the property
agent platforms, payment processors and merchants need before they let an autonomous system
touch money.
```

## Tags

```
AI Agents, Stablecoin, Payments, Solidity, Foundry, Smart Accounts, Agentic Commerce
```

## Links to fill in

| Field | Value |
| --- | --- |
| GitHub / GitLab | `https://github.com/Amburadullzz/agentpay` |
| Demo video | upload `demo/agentpay-demo.mp4` (2:59) to YouTube unlisted or Loom, paste the URL |
| Live demo | optional: the GitHub Pages URL once the workflow runs, or the repo README screenshots |

## Pre-submit checklist

- [ ] Repo is public and opens in a logged-out browser
- [ ] No `.env`, keys or keystores anywhere in the history (`git log -p --all -- .env wallets/ keys/`)
- [ ] README renders (architecture image + dashboard screenshot load)
- [ ] Video plays without login
- [ ] Contract addresses in the README match `deployments/aevum.json`
- [ ] Submitted before **11 Dec 2026, 08:00 UTC** (15:00 WIB) — submit early, portals get slow at the end

## Notes for the 3–5 min live call (if we make the top 5)

1. Open the dashboard, show the mandate (caps, threshold, expiry) and the vault balance.
2. Run `python agent/run_agent.py --once` live: one payment lands, one is refused by the cap.
3. Show the refusal reason in the agent log next to the revert on chain.
4. Pause the vault, run the agent again — it is blocked instantly. Unpause.
5. Open a receipt NFT and read the on-chain metadata.
6. Close on the threat model: the agent can waste gas, delay, and lie in its own log — it cannot move money outside the mandate.
