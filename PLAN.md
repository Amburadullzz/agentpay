# Aevum Builder Challenge #1 — build plan

Status: planning only (code must be written inside the build window: Nov 16 06:00 UTC → Dec 11 08:00 UTC).

## Event facts (verified 2026-11-11)

| Item | Value |
| --- | --- |
| Host | QDay Network (Aevum Testnet) |
| Cost | Free, fully online |
| Team | Solo or 2–4 |
| Registration | DoraHacks, opens Nov 16 06:00 UTC |
| Build window | Nov 16 06:00 UTC → Dec 11 08:00 UTC |
| Judging | Dec 12–14 · Demo Day Dec 15 06:00 UTC (top 5, 3–5 min live) |
| Prizes | $800 / $500 / $200 in USDT + fast track to mainnet builder program |
| Chain | Aevum Testnet, chainId **44005** (0xABE5) |
| RPC / WS | `https://rpc-test.qday.info` / `wss://rpc-test.qday.info` |
| Explorer | `explorer-test.qday.info` (Blockscout API works: `/api/v2/stats`) |
| Gas token | tQDAY, 18 dec, gas ~1 gwei, faucet 5 tQDAY / 24h / address |
| Test stablecoin | **tUSD8** `0x456569838f1d43009A91ebA4263147Afd7233483`, ERC-20, **6 decimals**, supply 3,217,400 (live now) |

Judging, 100 points: UX & presentation 15 · clear demo 10 · documentation 10 · innovation & originality 20 · technical quality & platform integration 15 · real-world utility 15 · safety, trust & controls 15.

Tracks offered: Invoice Payments, Payroll & Vesting, Crowdfunding, Confirmation of Payee, Decentralized Payments, Digital Ownership, Native AI Assistants, or another business payment tool.

## Pick: "AgentPay" — Native AI Assistants track

**Why this track.** QDay's whole thesis is agentic payments (x402 + AA wallets "coming soon"). An agent that pays real invoices under hard policy limits is the demo the judges are already primed to want, and it scores on every axis: innovation (agent-driven settlement), safety (caps/allowlist/approval), utility (invoice settlement is the boring real use case).

**One-sentence product.** A service provider issues an invoice on-chain; an AI agent reads it, checks it against its mandate, and pays it in tUSD8 through a policy-bound vault that can never exceed its limits — with a human approving anything above a threshold and every decision logged on-chain.

## Architecture

```
provider ──createInvoice()──► InvoiceRegistry (on Aevum)
                                   │  InvoiceCreated(id, payee, amount, memo, dueAt, salt)
agent (off-chain) ──reads invoice, matches to mandate──► PolicyVault
                                   │  pay(invoiceId) enforces:
                                   │    · payee allowlist
                                   │    · per-tx cap / rolling 24h cap
                                   │    · one payment per invoice (idempotent)
                                   │    · pause switch (kill switch)
                                   │    · approval threshold → requires approver signature
                                   └──► tUSD8.transferFrom / transfer → payee
                                        emits Paid(invoiceId, amount, by, at)
dashboard (viem) ── invoices · mandate editor · approvals · audit trail · pause
```

Contracts (Solidity 0.8.24, Foundry):

1. `InvoiceRegistry.sol` — create / cancel / read invoices, `paid` flag flipped only by the vault, events for every state change.
2. `PolicyVault.sol` — holds tUSD8, one mandate per agent key: allowlist, per-tx cap, daily cap, approval threshold, paused flag, nonce per invoice. Reentrancy-safe, checks-effects-interactions, custom errors.
3. `ApprovalRegistry.sol` (optional stretch) — EIP-712 approval signatures from a human approver for above-threshold invoices; replay-proof via invoiceId + nonce.

Off-chain:
- `agent/` — Python agent: poll invoices → validate (payee, amount, memo, due date) → simulate the call (`eth_call`) → decide pay/ask-approval/refuse → send via viem/ethers → log decision JSON.
- `web/` — Next.js + viem dashboard: invoice list, mandate editor, pending approvals, live audit trail, pause button.

## Safety controls (the 15-point block, spelled out)

- Hard caps enforced **on-chain**, not in the agent — an agent bug cannot overspend.
- Payee allowlist set by the human, not the agent.
- Idempotency: an invoice can be paid once; replay of the same calldata reverts.
- Approval threshold: above X tUSD8 the vault requires a human EIP-712 signature.
- Kill switch: human-only `pause()`; agent cannot unpause.
- Every refusal is logged with a reason (`REFUSED_CAP`, `REFUSED_PAYEE`, `REFUSED_DUPLICATE`).
- No private keys in the web app; agent key is separate from the human approver key.

## Build schedule (25 days)

| Window | Work |
| --- | --- |
| Nov 16–18 | Foundry scaffold, both contracts, full test suite (caps, replay, pause, allowlist, approval) |
| Nov 19–21 | Deploy to Aevum, verify on explorer, faucet tQUSD8 to test wallets, smoke-test transfers |
| Nov 22–26 | Agent loop + mandate engine; end-to-end: invoice → agent decision → payment → event |
| Nov 27–30 | Dashboard: invoices, mandate editor, approvals, audit trail, pause |
| Dec 1–4 | Demo script + 3–5 min video, seed data, edge-case pass (over-cap, wrong payee, duplicate, paused) |
| Dec 5–8 | Docs: problem, architecture, workflows, technologies; README with one-command run |
| Dec 9–10 | Polish, judge-criteria self-audit against the 100-point rubric, submission checklist |
| Dec 11 | Submit before 08:00 UTC |

## Risks and mitigations

- **Faucet is 5 tQDAY / 24h / address and needs a connected wallet** (RainbowKit on `faucet.qday.info`, likely with a mainnet-balance check) → the user claims from their own wallet, entering the agent address; budget gas: deploy + testnet runs only when code is final, everything else on Anvil.
- **"All code written in the window"** → nothing is committed before Nov 16; this document is planning, which the rules allow.
- **Judging weights innovation + safety heavily** → the demo must show a refusal and a pause, not just a happy path.
- **tUSD8 has 6 decimals** → every amount in the UI/agent must be scaled by 1e6; the classic bug here is a 1e18 assumption.
- **Solo entry** → scope discipline: one flow done well beats three half-built tracks.

## What the user must provide

1. DoraHacks account (registration + submission happen there).
2. Public GitHub repo (can be created Nov 16; the code must land inside the window).
3. A wallet address for the faucet (tQDAY + tUSD8), plus a second address for the approver role.
