"""Batch payroll on top of AgentPay.

One invoice per payee, one agent pass, one report. Every payment still goes through the same
per-invoice checks: a payee that is not allowlisted is refused, an amount over the per-tx cap is
refused, and the daily budget stops the run when it is exhausted — the batch does not bypass
anything, it just repeats the single-payment flow.

    python agent/payroll.py --csv demo/payroll.csv --allowlist --execute
    python agent/payroll.py --csv demo/payroll.csv --dry-run

CSV columns: name,address,amount,memo   (amount in tUSD8, e.g. 0.05)
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

from eth_account import Account
from web3 import Web3

sys.path.insert(0, str(Path(__file__).parent))

from agentpay import PAY, REFUSE, REGISTRY_ABI, VAULT_ABI, fmt, from_env  # noqa: E402

UNIT = 10**6


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if not row.get("address") or not row.get("amount"):
            raise SystemExit(f"row missing address/amount: {row}")
    return rows


def owner_allowlist(w3: Web3, addresses: list[str]) -> None:
    """Owner-only setup: put every payee on the allowlist. Payroll cannot do this itself."""
    owner = Account.from_key(os.environ["OWNER_PRIVATE_KEY"])
    vault = w3.eth.contract(address=Web3.to_checksum_address(os.environ["VAULT_ADDRESS"]), abi=VAULT_ABI)

    for addr in addresses:
        tx = vault.functions.setPayeeAllowed(Web3.to_checksum_address(addr), True).build_transaction({
            "from": owner.address,
            "nonce": w3.eth.get_transaction_count(owner.address, "pending"),
            "chainId": w3.eth.chain_id,
            "gas": 200_000,
            "maxFeePerGas": w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": w3.eth.gas_price,
        })
        signed = w3.eth.account.sign_transaction(tx, owner.key)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(h, timeout=180)
        if receipt.status != 1:
            raise SystemExit(f"allowlist tx reverted for {addr}")
        print(f"  allowlisted {addr}")


def issue(w3: Web3, row: dict) -> int:
    provider = Account.from_key(os.environ["PROVIDER_PRIVATE_KEY"])
    registry = w3.eth.contract(
        address=Web3.to_checksum_address(os.environ["REGISTRY_ADDRESS"]), abi=REGISTRY_ABI
    )
    amount = int(Decimal(row["amount"]) * UNIT)
    memo_hash = Web3.keccak(text=row.get("memo") or f"payroll {row['name']}")

    tx = registry.functions.createInvoice(
        Web3.to_checksum_address(row["address"]), amount, memo_hash, 0
    ).build_transaction({
        "from": provider.address,
        "nonce": w3.eth.get_transaction_count(provider.address, "pending"),
        "chainId": w3.eth.chain_id,
        "gas": 300_000,
        "maxFeePerGas": w3.eth.gas_price * 2,
        "maxPriorityFeePerGas": w3.eth.gas_price,
    })
    signed = w3.eth.account.sign_transaction(tx, provider.key)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    if w3.eth.wait_for_transaction_receipt(h, timeout=180).status != 1:
        raise SystemExit(f"invoice creation reverted for {row['name']}")
    return registry.functions.invoiceCount().call()


def main() -> int:
    p = argparse.ArgumentParser(description="AgentPay batch payroll")
    p.add_argument("--csv", required=True, help="name,address,amount,memo")
    p.add_argument("--allowlist", action="store_true", help="owner: allowlist every payee first")
    p.add_argument("--execute", action="store_true", help="actually pay (default is a dry run)")
    p.add_argument("--dry-run", action="store_true", help="decide only, never send")
    args = p.parse_args()

    rows = load_rows(Path(args.csv))
    total = sum(Decimal(r["amount"]) for r in rows)
    print(f"payroll: {len(rows)} payees · total {total} tUSD8\n")

    agent = from_env()
    w3 = agent.w3

    if args.allowlist:
        print("owner: allowlisting payees")
        owner_allowlist(w3, [r["address"] for r in rows])

    ids = []
    for row in rows:
        invoice_id = issue(w3, row)
        ids.append(invoice_id)
        print(f"  invoice #{invoice_id:<3} {fmt(int(Decimal(row['amount']) * UNIT)):>8} tUSD8 → {row['name']} ({row['address']})")

    print("\nagent pass:")
    mandate = agent.mandate()
    paused = agent.vault.functions.paused().call()
    results = []

    for row, invoice_id in zip(rows, ids):
        inv = agent.invoice(invoice_id)
        decision = agent.decide(inv, mandate, paused)

        if decision.action == PAY and args.execute and not args.dry_run:
            try:
                decision.tx_hash = agent.pay(invoice_id)
                decision.reason = "PAID"
            except Exception as exc:  # noqa: BLE001
                decision.action = REFUSE
                decision.reason = str(exc)[:80]
        elif decision.action == PAY:
            decision.reason = "WOULD_PAY"

        agent.log(decision)
        results.append((row["name"], inv.amount, decision))
        mark = "✓" if decision.action == PAY else "✗"
        print(f"  {mark} {row['name']:<14} {fmt(inv.amount):>8} tUSD8  {decision.action:<8} {decision.reason}")

    paid = [r for r in results if r[2].action == PAY]
    refused = [r for r in results if r[2].action != PAY]
    paid_total = sum(a for _, a, d in paid if d.action == PAY)

    print(f"\n{len(paid)}/{len(results)} paid · {fmt(paid_total)} tUSD8 settled")
    if refused:
        print("refused:")
        for name, amount, d in refused:
            print(f"  - {name} ({fmt(amount)}): {d.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
