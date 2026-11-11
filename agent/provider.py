"""Provider console: issue invoices on-chain.

    python agent/provider.py --payee 0xProvider --amount 0.15 --memo "GPU rental, Nov"
    python agent/provider.py --list
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3

sys.path.insert(0, str(Path(__file__).parent))

from agentpay import DECIMALS, REGISTRY_ABI, fmt  # noqa: E402

UNIT = 10**DECIMALS


def main() -> int:
    p = argparse.ArgumentParser(description="AgentPay provider console")
    p.add_argument("--payee", help="address that receives the money")
    p.add_argument("--amount", help="amount in tUSD8, e.g. 0.15")
    p.add_argument("--memo", default="", help="human-readable memo (hashed on-chain)")
    p.add_argument("--due-in-hours", type=int, default=0, help="0 = no deadline")
    p.add_argument("--list", action="store_true", help="list invoices")
    args = p.parse_args()

    w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"], request_kwargs={"timeout": 30}))
    registry = w3.eth.contract(
        address=Web3.to_checksum_address(os.environ["REGISTRY_ADDRESS"]), abi=REGISTRY_ABI
    )

    if args.list:
        count = registry.functions.invoiceCount().call()
        for i in range(1, count + 1):
            inv = registry.functions.getInvoice(i).call()
            state = "paid" if inv[5] else ("cancelled" if inv[6] else "open")
            print(f"#{i:<3} {fmt(inv[2]):>10} tUSD8 → {inv[1]}  {state}")
        return 0

    if not (args.payee and args.amount):
        raise SystemExit("--payee and --amount are required unless --list")

    acct = Account.from_key(os.environ["PROVIDER_PRIVATE_KEY"])
    amount = int(round(float(args.amount) * UNIT))
    memo_hash = Web3.keccak(text=args.memo) if args.memo else b"\x00" * 32
    due_at = int(time.time()) + args.due_in_hours * 3600 if args.due_in_hours else 0

    fn = registry.functions.createInvoice(
        Web3.to_checksum_address(args.payee), amount, memo_hash, due_at
    )
    tx = fn.build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": w3.eth.chain_id,
            "gas": 300_000,
            "maxFeePerGas": w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": w3.eth.gas_price,
        }
    )
    signed = w3.eth.account.sign_transaction(tx, acct.key)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    if receipt.status != 1:
        raise SystemExit(f"invoice creation reverted: {h.hex()}")

    invoice_id = registry.functions.invoiceCount().call()
    print(f"invoice #{invoice_id} created for {fmt(amount)} tUSD8 → {args.payee}")
    print(f"tx {h.hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
