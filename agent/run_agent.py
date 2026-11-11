"""Run the agent: read open invoices, decide, pay what the mandate allows.

Usage:
    python agent/run_agent.py --once            # one pass, then exit
    python agent/run_agent.py --watch           # loop every N seconds
    python agent/run_agent.py --once --dry-run  # decide only, never send

Environment: see .env.example
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agentpay import ASK_APPROVAL, PAY, REFUSE, SKIP, fmt, from_env  # noqa: E402

APPROVALS_DIR = Path(__file__).parent / "approvals"


def _short(addr: str) -> str:
    return f"{addr[:6]}…{addr[-4:]}"


def _load_approval(invoice_id: int) -> dict | None:
    path = APPROVALS_DIR / f"{invoice_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _submit_approval(agent, invoice_id: int, approval: dict) -> str:
    """Submit a payment the owner already signed off-chain."""
    return agent.pay_with_approval(
        invoice_id, approval["deadline"], bytes.fromhex(approval["sig"])
    )


def run_once(agent, dry_run: bool = False) -> list:
    mandate = agent.mandate()
    paused = agent.vault.functions.paused().call()
    invoices = agent.open_invoices()

    print(
        f"\nmandate: cap {fmt(mandate.per_tx_cap)}/tx · {fmt(mandate.daily_cap)}/day · "
        f"approval ≥ {fmt(mandate.approval_threshold)} · spent today {fmt(mandate.day_spent)}"
        f"{' · PAUSED' if paused else ''}"
    )
    if not invoices:
        print("no open invoices")
        return []

    decisions = []
    for inv in invoices:
        decision = agent.decide(inv, mandate, paused)

        if decision.action == PAY and not dry_run:
            try:
                decision.tx_hash = agent.pay(inv.id)
                decision.reason = "PAID"
            except Exception as exc:  # noqa: BLE001
                decision.action = REFUSE
                decision.reason = str(exc)[:90]

        elif decision.action == ASK_APPROVAL and not dry_run:
            approval = _load_approval(inv.id)
            if approval:
                try:
                    decision.tx_hash = _submit_approval(agent, inv.id, approval)
                    decision.reason = "PAID_WITH_APPROVAL"
                    APPROVALS_DIR.joinpath(f"{inv.id}.json").unlink(missing_ok=True)
                except Exception as exc:  # noqa: BLE001
                    decision.action = REFUSE
                    decision.reason = str(exc)[:90]
            else:
                decision.reason = "AWAITING_OWNER_SIGNATURE"

        agent.log(decision)
        decisions.append(decision)

        mark = {PAY: "✓", ASK_APPROVAL: "?", REFUSE: "✗", SKIP: "-"}.get(decision.action, "·")
        tx = f"  tx {decision.tx_hash[:14]}…" if decision.tx_hash else ""
        print(
            f" {mark} #{inv.id:<3} {fmt(inv.amount):>10} tUSD8 → {_short(inv.payee)}"
            f"  {decision.action:<13} {decision.reason}{tx}"
        )
    return decisions


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentPay agent")
    parser.add_argument("--once", action="store_true", help="single pass")
    parser.add_argument("--watch", action="store_true", help="loop until interrupted")
    parser.add_argument("--interval", type=int, default=15, help="seconds between passes")
    parser.add_argument("--dry-run", action="store_true", help="decide, never send")
    args = parser.parse_args()

    agent = from_env()

    if args.watch:
        try:
            while True:
                run_once(agent, args.dry_run)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nstopped")
            return 0

    run_once(agent, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
