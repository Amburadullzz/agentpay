"""Attack simulation against the live AgentPay vault.

Every attack is attempted as the agent (the untrusted key) and simulated with eth_call, so the
output is the chain's own refusal reason — not a claim about what would happen.

    .venv/bin/python agent/attack_sim.py

Exit code is 0 only if every attack was refused for the expected reason.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from eth_account import Account
from eth_utils import keccak
from web3 import Web3

sys.path.insert(0, str(Path(__file__).parent))

from agentpay import REGISTRY_ABI, VAULT_ABI, fmt  # noqa: E402

UNIT = 10**6

ERROR_SIGNATURES = [
    "PayeeNotAllowed()",
    "CapExceeded()",
    "DailyCapExceeded()",
    "AlreadyPaid()",
    "AlreadyCancelled()",
    "VaultPaused()",
    "NotAgent()",
    "SessionExpired()",
    "ApprovalRequired()",
    "ApprovalExpired()",
    "BadApproval()",
    "InvoiceExpired()",
    "InsufficientVaultBalance()",
    "MustBePaused()",
    "OwnableUnauthorizedAccount(address)",
    "NotVault()",
]

SELECTORS = {keccak(text=sig)[:4].hex(): sig.split("(")[0] for sig in ERROR_SIGNATURES}


def _reason(exc: Exception) -> str:
    """Turn whatever web3 hands back into the contract's own error name."""
    text = str(exc)
    for marker in ("execution reverted:", "revert "):
        if marker in text:
            text = text.split(marker, 1)[1]
    import re as _re
    for sel in _re.findall(r"0x[0-9a-fA-F]{8}", text):
        name = SELECTORS.get(sel.lower()[2:])
        if name:
            return name
    return text.strip().strip("'\"")[:80]


def main() -> int:
    rpc = os.environ.get("RPC_URL", "https://rpc-test.qday.info")
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    vault_addr = Web3.to_checksum_address(os.environ["VAULT_ADDRESS"])
    registry_addr = Web3.to_checksum_address(os.environ["REGISTRY_ADDRESS"])

    vault = w3.eth.contract(address=vault_addr, abi=VAULT_ABI)
    registry = w3.eth.contract(address=registry_addr, abi=REGISTRY_ABI)

    agent_key = os.environ["AGENT_PRIVATE_KEY"]
    agent = Account.from_key(agent_key).address

    owner = vault.functions.owner().call()

    print(f"vault   {vault_addr}")
    print(f"agent   {agent}  (the untrusted key)")
    print(f"owner   {owner}\n")

    results: list[tuple[str, str, str, bool]] = []
    provider = Account.from_key(os.environ["PROVIDER_PRIVATE_KEY"])

    def create_invoice(payee: str, amount: int) -> int:
        """Issue a fixture invoice from the provider so every attack has something to hit."""
        fn = registry.functions.createInvoice(
            Web3.to_checksum_address(payee), amount, Web3.keccak(text="attack fixture"), 0
        )
        tx = fn.build_transaction({
            "from": provider.address, "nonce": w3.eth.get_transaction_count(provider.address, "pending"),
            "chainId": w3.eth.chain_id, "gas": 300_000,
            "maxFeePerGas": w3.eth.gas_price * 2, "maxPriorityFeePerGas": w3.eth.gas_price,
        })
        signed = w3.eth.account.sign_transaction(tx, provider.key)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(h, timeout=180)
        return registry.functions.invoiceCount().call()

    def attempt(label: str, expected: str, fn) -> None:
        try:
            fn().call({"from": agent})
            results.append((label, expected, "NOT BLOCKED — call succeeded", False))
        except Exception as exc:  # noqa: BLE001
            got = _reason(exc)
            ok = expected.lower() in got.lower()
            results.append((label, expected, got, ok))

    # 1. pay an invoice whose payee is not on the allowlist
    payee_rogue = Web3.to_checksum_address("0xbadbadbadbadbadbadbadbadbadbadbadbadbad0")
    count = registry.functions.invoiceCount().call()
    print(f"invoices on chain: {count}")

    # find an open invoice paid to a non-allowlisted address, if any; otherwise describe
    rogue_invoice = None
    for i in range(1, count + 1):
        inv = registry.functions.getInvoice(i).call()
        if not inv[5] and not inv[6] and not vault.functions.isPayeeAllowed(inv[1]).call():
            rogue_invoice = i
            break

    if not rogue_invoice:
        rogue_invoice = create_invoice(payee_rogue, 100_000)
        print(f"fixture: created invoice #{rogue_invoice} to a non-allowlisted payee")
    attempt(f"pay invoice #{rogue_invoice} to a non-allowlisted payee", "PayeeNotAllowed",
            lambda: vault.functions.pay(rogue_invoice))

    # 2. pay an invoice above the per-transaction cap
    over_cap = None
    cap = vault.functions.mandateOf(agent).call()[1]
    for i in range(1, count + 1):
        inv = registry.functions.getInvoice(i).call()
        if not inv[5] and not inv[6] and inv[2] > cap and vault.functions.isPayeeAllowed(inv[1]).call():
            over_cap = i
            break
    if not over_cap:
        over_cap = create_invoice(provider.address, min(int(cap) * 2, 10**9))
        print(f"fixture: created invoice #{over_cap} above the per-tx cap")
    attempt(f"pay invoice #{over_cap} over the per-tx cap ({fmt(cap)})", "CapExceeded",
            lambda: vault.functions.pay(over_cap))

    # 3. replay an already-paid invoice
    paid_invoice = None
    for i in range(1, count + 1):
        if registry.functions.getInvoice(i).call()[5]:
            paid_invoice = i
            break
    if paid_invoice:
        attempt(f"replay paid invoice #{paid_invoice}", "AlreadyPaid",
                lambda: vault.functions.pay(paid_invoice))
    else:
        results.append(("replay a paid invoice", "AlreadyPaid", "skipped: nothing paid yet", True))

    # 4. raise its own limits
    attempt("call setMandate as the agent", "OwnableUnauthorizedAccount",
            lambda: vault.functions.setMandate(agent, 10**9, 10**9, 0, 0))

    # 5. unpause / pause the vault
    attempt("call pause as the agent", "OwnableUnauthorizedAccount", lambda: vault.functions.pause())

    # 6. withdraw the balance
    attempt("call withdraw as the agent", "OwnableUnauthorizedAccount",
            lambda: vault.functions.withdraw(1))

    # 7. allow a new payee
    attempt("call setPayeeAllowed as the agent", "OwnableUnauthorizedAccount",
            lambda: vault.functions.setPayeeAllowed(payee_rogue, True))

    # 8. submit an approval signed by a key that is not the owner
    approval_invoice = None
    threshold = vault.functions.mandateOf(agent).call()[3]
    for i in range(1, count + 1):
        inv = registry.functions.getInvoice(i).call()
        if (not inv[5] and not inv[6] and inv[2] >= threshold and inv[2] <= cap
                and vault.functions.isPayeeAllowed(inv[1]).call()):
            approval_invoice = i
            break
    if not approval_invoice:
        approval_invoice = create_invoice(provider.address, int(threshold))
        print(f"fixture: created invoice #{approval_invoice} above the approval threshold")
    if approval_invoice:
        inv = registry.functions.getInvoice(approval_invoice).call()
        nonce = vault.functions.mandateOf(agent).call()[7]
        deadline = w3.eth.get_block("latest").timestamp + 3600
        digest = vault.functions.approvalDigest(
            approval_invoice, inv[2], inv[1], nonce, deadline
        ).call()
        rogue = Account.from_key("0x" + "11" * 32)
        sig = Account.unsafe_sign_hash(bytes(digest), rogue.key).signature
        attempt(f"pay invoice #{approval_invoice} with a forged approval", "BadApproval",
                lambda: vault.functions.payWithApproval(approval_invoice, deadline, sig))


    # ---------------------------------------------------------------- report
    print(f"\n{'attack':<52} {'expected':<26} {'result'}")
    print("-" * 120)
    for label, expected, got, ok in results:
        mark = "BLOCKED" if ok else "!! FAILED"
        print(f"{label:<52} {expected:<26} {mark}: {got}")

    failed = [r for r in results if not r[3]]
    print(f"\n{len(results) - len(failed)}/{len(results)} attacks refused for the expected reason")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
