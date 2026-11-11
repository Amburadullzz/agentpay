# AgentPay — demo script (3–5 min) + submission checklist

## Demo beats (judges score "clear, well-structured demo" = 10 pts)

| Time | Beat | What is on screen |
| --- | --- | --- |
| 0:00 | Problem | "Agents can already act; they can't be trusted with a card. Every payment needs a limit the agent cannot argue with." |
| 0:20 | Setup | Vault funded with 500 tUSD8, mandate: 50/tx, 150/day, approval above 120. Explorer link for both deploys. |
| 0:40 | Happy path | Provider creates invoice #1 for 40 tUSD8 → agent reads it, checks mandate, calls `pay(1)` → dashboard flips to PAID, explorer shows the transfer. |
| 1:20 | **Refusal** | Invoice #2 for 200 tUSD8 → agent refuses on its own: `CapExceeded`. Log line shows the exact reason and the mandate values it compared. |
| 1:50 | **Human approval** | Invoice #3 for 140 tUSD8 (above the 120 threshold) → agent stops and asks. Owner signs the EIP-712 approval, agent submits `payWithApproval` → PAID, nonce bumped. |
| 2:40 | **Replay defence** | Re-run the same approval → `BadApproval`. Re-run `pay(1)` → `AlreadyPaid`. |
| 3:00 | **Kill switch** | Owner pauses → agent tries invoice #4 → `VaultPaused`, dashboard shows PAUSED. Unpause, payment goes through. |
| 3:30 | Audit trail | Filtered event log: every attempt, including refusals, with timestamps and reasons. |

Every beat is a test that already exists in `forge test` — say that out loud; it converts a demo into evidence.

## Recording notes

- 1280×720, one browser window, terminal beside it; no dead air while a tx confirms (cut or speed up 2×).
- Show the explorer at least twice: deploy and one payment. Deliverable #2 ("evidence your app uses QDay infrastructure") is scored from those frames.
- End on the mandate screen, not the logo — the last frame is what a judge remembers.

## Submission checklist (DoraHacks, due Dec 11 08:00 UTC)

- [ ] Public GitHub repo, OSI license, clean history (code only from Nov 16 onward)
- [ ] README: one-paragraph problem, architecture diagram, one-command run, deployed addresses, test table (feature → test name)
- [ ] Deployed contracts on Aevum testnet + explorer links
- [ ] Live demo: hosted UI **or** Docker image **or** a recorded video — pick two, they overlap in scoring
- [ ] Docs folder: problem, architecture, core workflows, technologies (deliverable #4)
- [ ] Safety section: caps, allowlist, idempotency, approval, pause — each mapped to a test
- [ ] 3–5 min demo video uploaded (unlisted YouTube or Loom)
- [ ] Screenshot of the mandate config in the UI (judges like a single frame that shows the controls)
- [ ] Submit on DoraHacks before the deadline; keep the tx hashes in the README in case the indexer lags

## Judge-criteria self-audit (score yourself out of 100 before submitting)

| Criterion | Pts | How AgentPay earns it |
| --- | --- | --- |
| UX & presentation | 15 | One screen: invoices, mandate, approvals, audit trail; no wallet jargon in the happy path |
| Clear demo | 10 | Script above, every beat pre-tested |
| Documentation | 10 | README + docs/ + diagram + test table |
| Innovation & originality | 20 | Agent-initiated settlement with on-chain, unbypassable policy — not a payment form |
| Technical quality & integration | 15 | Two audited-pattern contracts, 30+ tests, ≥90% coverage, real tUSD8 transfers |
| Real-world utility | 15 | Invoice settlement is the actual first use case for agent payments |
| Safety, trust & controls | 15 | Caps + allowlist + idempotency + EIP-712 approval + pause, all on-chain |
