"""Owner console: mandate, allowlist, approvals, pause.

The owner key is the only key with authority. It is never used by the agent process.

    python agent/owner.py state
    python agent/owner.py mandate --per-tx 0.3 --daily 0.8 --threshold 0.2 [--valid-days 7]
    python agent/owner.py allow 0xPayee
    python agent/owner.py approve 3            # signs an EIP-712 approval for invoice #3
    python agent/owner.py pause | unpause
    python agent/owner.py revoke 0xAgent
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3

sys.path.insert(0, str(Path(__file__).parent))

from agentpay import DECIMALS, REGISTRY_ABI, VAULT_ABI, fmt  # noqa: E402

UNIT = 10**DECIMALS
APPROVALS_DIR = Path(__file__).parent / "approvals"


def _w3() -> Web3:
    return Web3(Web3.HTTPProvider(os.environ["RPC_URL"], request_kwargs={"timeout": 30}))


def _ctx():
    w3 = _w3()
    vault = w3.eth.contract(address=Web3.to_checksum_address(os.environ["VAULT_ADDRESS"]), abi=VAULT_ABI)
    registry = w3.eth.contract(
        address=Web3.to_checksum_address(os.environ["REGISTRY_ADDRESS"]), abi=REGISTRY_ABI
    )
    acct = Account.from_key(os.environ["OWNER_PRIVATE_KEY"])
    return w3, vault, registry, acct


def _send(w3, acct, fn) -> str:
    tx = fn.build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": w3.eth.chain_id,
            "gas": 400_000,
            "maxFeePerGas": w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": w3.eth.gas_price,
        }
    )
    signed = w3.eth.account.sign_transaction(tx, acct.key)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f"reverted: {h.hex()}")
    return h.hex()


def cmd_state(_args) -> None:
    _, vault, _, acct = _ctx()
    agent = Web3.to_checksum_address(os.environ["AGENT_ADDRESS"])
    m = vault.functions.mandateOf(agent).call()
    print(f"owner          {acct.address}")
    print(f"agent          {agent}")
    print(f"paused         {vault.functions.paused().call()}")
    print(f"active session {m[0]}")
    print(f"per-tx cap     {fmt(m[1])} tUSD8")
    print(f"daily cap      {fmt(m[2])} tUSD8")
    print(f"threshold      {fmt(m[3])} tUSD8")
    print(f"valid until    {m[4] or 'no expiry'}")
    print(f"spent today    {fmt(m[6])} tUSD8")
    print(f"nonce          {m[7]}")
    token = Web3.to_checksum_address(os.environ["TOKEN_ADDRESS"])
    from agentpay import TOKEN_ABI  # local import keeps the module surface small

    t = _w3().eth.contract(address=token, abi=TOKEN_ABI)
    print(f"vault balance  {fmt(t.functions.balanceOf(vault.address).call())} tUSD8")


def cmd_mandate(args) -> None:
    w3, vault, _, acct = _ctx()
    agent = Web3.to_checksum_address(os.environ["AGENT_ADDRESS"])
    per_tx = int(round(float(args.per_tx) * UNIT))
    daily = int(round(float(args.daily) * UNIT))
    threshold = int(round(float(args.threshold) * UNIT))
    valid_until = int(time.time()) + args.valid_days * 86400 if args.valid_days else 0
    h = _send(w3, acct, vault.functions.setMandate(agent, per_tx, daily, threshold, valid_until))
    print(f"mandate set  tx {h}")


def cmd_allow(args) -> None:
    w3, vault, _, acct = _ctx()
    h = _send(
        w3, acct, vault.functions.setPayeeAllowed(Web3.to_checksum_address(args.payee), True)
    )
    print(f"payee allowed  tx {h}")


def cmd_approve(args) -> None:
    w3, vault, registry, acct = _ctx()
    inv = registry.functions.getInvoice(args.invoice_id).call()
    if inv[5]:
        raise SystemExit("invoice already paid")
    agent = Web3.to_checksum_address(os.environ["AGENT_ADDRESS"])
    nonce = vault.functions.mandateOf(agent).call()[7]
    deadline = int(time.time()) + args.valid_minutes * 60
    digest = vault.functions.approvalDigest(
        args.invoice_id, inv[2], inv[1], nonce, deadline
    ).call()
    signed = Account.unsafe_sign_hash(bytes(digest), acct.key)

    APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "invoiceId": args.invoice_id,
        "amount": inv[2],
        "amountHuman": fmt(inv[2]),
        "payee": inv[1],
        "nonce": nonce,
        "deadline": deadline,
        "sig": signed.signature.hex(),
    }
    path = APPROVALS_DIR / f"{args.invoice_id}.json"
    path.write_text(json.dumps(payload, indent=2))
    print(f"signed invoice #{args.invoice_id} for {fmt(inv[2])} tUSD8")
    print(f"approval saved to {path}")
    print("the agent will submit it on its next pass")


def cmd_pause(args) -> None:
    w3, vault, _, acct = _ctx()
    fn = vault.functions.pause() if args.action == "pause" else vault.functions.unpause()
    print(f"{args.action}  tx {_send(w3, acct, fn)}")


def cmd_revoke(args) -> None:
    w3, vault, _, acct = _ctx()
    h = _send(w3, acct, vault.functions.revokeSession(Web3.to_checksum_address(args.agent)))
    print(f"session revoked  tx {h}")


def main() -> int:
    p = argparse.ArgumentParser(description="AgentPay owner console")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("state").set_defaults(fn=cmd_state)

    m = sub.add_parser("mandate")
    m.add_argument("--per-tx", required=True)
    m.add_argument("--daily", required=True)
    m.add_argument("--threshold", required=True)
    m.add_argument("--valid-days", type=int, default=0)
    m.set_defaults(fn=cmd_mandate)

    a = sub.add_parser("allow")
    a.add_argument("payee")
    a.set_defaults(fn=cmd_allow)

    ap = sub.add_parser("approve")
    ap.add_argument("invoice_id", type=int)
    ap.add_argument("--valid-minutes", type=int, default=60)
    ap.set_defaults(fn=cmd_approve)

    for name in ("pause", "unpause"):
        s = sub.add_parser(name)
        s.set_defaults(fn=cmd_pause, action=name)

    r = sub.add_parser("revoke")
    r.add_argument("agent")
    r.set_defaults(fn=cmd_revoke)

    args = p.parse_args()
    args.fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
