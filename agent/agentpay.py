"""AgentPay agent core.

The agent is a *proposer*: it reads invoices, compares them against its mandate and asks the
vault to pay. It never holds owner rights — caps, allowlist, idempotency, approval threshold,
session expiry and the pause switch are enforced by the contract, not by this file.

The decision function mirrors the vault's check order so a refusal is predicted and logged with
a precise reason instead of being discovered as a failed transaction.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from web3 import Web3

DECIMALS = 6
UNIT = 10**DECIMALS

REGISTRY_ABI = [
    {
        "name": "invoiceCount",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getInvoice",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "id", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "issuer", "type": "address"},
                    {"name": "payee", "type": "address"},
                    {"name": "amount", "type": "uint96"},
                    {"name": "memoHash", "type": "bytes32"},
                    {"name": "dueAt", "type": "uint64"},
                    {"name": "paid", "type": "bool"},
                    {"name": "cancelled", "type": "bool"},
                ],
            }
        ],
    },
    {
        "name": "createInvoice",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "payee", "type": "address"},
            {"name": "amount", "type": "uint96"},
            {"name": "memoHash", "type": "bytes32"},
            {"name": "dueAt", "type": "uint64"},
        ],
        "outputs": [{"name": "id", "type": "uint256"}],
    },
]

VAULT_ABI = [
    {
        "name": "mandateOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "active", "type": "bool"},
                    {"name": "perTxCap", "type": "uint96"},
                    {"name": "dailyCap", "type": "uint96"},
                    {"name": "approvalThreshold", "type": "uint96"},
                    {"name": "validUntil", "type": "uint64"},
                    {"name": "dayStart", "type": "uint64"},
                    {"name": "daySpent", "type": "uint96"},
                    {"name": "nonce", "type": "uint32"},
                ],
            }
        ],
    },
    {
        "name": "isPayeeAllowed",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {"name": "paused", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"name": "", "type": "bool"}]},
    {
        "name": "pay",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "invoiceId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "payWithApproval",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "invoiceId", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "sig", "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "approvalDigest",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "invoiceId", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
            {"name": "payee", "type": "address"},
            {"name": "nonce", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {"name": "pause", "type": "function", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
    {"name": "unpause", "type": "function", "stateMutability": "nonpayable", "inputs": [], "outputs": []},
    {
        "name": "setMandate",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agent", "type": "address"},
            {"name": "perTxCap", "type": "uint96"},
            {"name": "dailyCap", "type": "uint96"},
            {"name": "approvalThreshold", "type": "uint96"},
            {"name": "validUntil", "type": "uint64"},
        ],
        "outputs": [],
    },
    {
        "name": "setPayeeAllowed",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "payee", "type": "address"},
            {"name": "allowed", "type": "bool"},
        ],
        "outputs": [],
    },
    {
        "name": "revokeSession",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [],
    },
]

TOKEN_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]

PAY = "PAY"
ASK_APPROVAL = "ASK_APPROVAL"
REFUSE = "REFUSE"
SKIP = "SKIP"


def fmt(amount: int) -> str:
    """Raw 6-decimal units to a human string."""
    return f"{Decimal(amount) / UNIT:.6f}".rstrip("0").rstrip(".") or "0"


@dataclass
class Invoice:
    id: int
    issuer: str
    payee: str
    amount: int
    memo_hash: str
    due_at: int
    paid: bool
    cancelled: bool

    @property
    def amount_human(self) -> str:
        return fmt(self.amount)


@dataclass
class Mandate:
    active: bool
    per_tx_cap: int
    daily_cap: int
    approval_threshold: int
    valid_until: int
    day_start: int
    day_spent: int
    nonce: int


@dataclass
class Decision:
    invoice_id: int
    action: str
    reason: str
    amount: int
    payee: str
    tx_hash: str | None = None
    at: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class AgentPay:
    def __init__(
        self,
        rpc_url: str,
        vault: str,
        agent_address: str,
        private_key: str | None = None,
        log_path: str | Path | None = None,
    ):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        if not self.w3.is_connected():
            raise RuntimeError(f"cannot reach RPC {rpc_url}")
        self.vault_address = Web3.to_checksum_address(vault)
        self.vault = self.w3.eth.contract(address=self.vault_address, abi=VAULT_ABI)
        self.agent = Web3.to_checksum_address(agent_address)
        self.account = self.w3.eth.account.from_key(private_key) if private_key else None
        if self.account and self.account.address != self.agent:
            raise RuntimeError(
                f"agent address {self.agent} does not match the signing key {self.account.address}"
            )
        self.log_path = Path(log_path) if log_path else None
        self.registry_address: str | None = None
        self.registry_contract = None
        self.token_address: str | None = None

    # ------------------------------------------------------------------ reads

    def set_registry(self, address: str) -> None:
        self.registry_address = Web3.to_checksum_address(address)
        self.registry_contract = self.w3.eth.contract(address=self.registry_address, abi=REGISTRY_ABI)

    def token_balance(self, address: str) -> int:
        token = self.w3.eth.contract(address=self.token_address, abi=TOKEN_ABI)
        return token.functions.balanceOf(Web3.to_checksum_address(address)).call()

    def mandate(self) -> Mandate:
        m = self.vault.functions.mandateOf(self.agent).call()
        return Mandate(
            active=m[0],
            per_tx_cap=m[1],
            daily_cap=m[2],
            approval_threshold=m[3],
            valid_until=m[4],
            day_start=m[5],
            day_spent=m[6],
            nonce=m[7],
        )

    def invoice(self, invoice_id: int) -> Invoice:
        inv = self.registry_contract.functions.getInvoice(invoice_id).call()
        return Invoice(
            id=invoice_id,
            issuer=inv[0],
            payee=inv[1],
            amount=inv[2],
            memo_hash="0x" + inv[3].hex() if isinstance(inv[3], bytes) else str(inv[3]),
            due_at=inv[4],
            paid=inv[5],
            cancelled=inv[6],
        )

    def open_invoices(self) -> list[Invoice]:
        count = self.registry_contract.functions.invoiceCount().call()
        out = []
        for i in range(1, count + 1):
            inv = self.invoice(i)
            if not inv.paid and not inv.cancelled:
                out.append(inv)
        return out

    # --------------------------------------------------------------- decide

    def decide(self, inv: Invoice, mandate: Mandate | None = None, paused: bool | None = None) -> Decision:
        """Mirror of the vault's check order. Never sends anything."""
        m = mandate or self.mandate()
        if paused is None:
            paused = self.vault.functions.paused().call()

        def d(action: str, reason: str) -> Decision:
            return Decision(
                invoice_id=inv.id,
                action=action,
                reason=reason,
                amount=inv.amount,
                payee=inv.payee,
                at=int(time.time()),
            )

        if paused:
            return d(REFUSE, "VAULT_PAUSED")
        if not m.active:
            return d(REFUSE, "NOT_AGENT")
        if m.valid_until and time.time() > m.valid_until:
            return d(REFUSE, "SESSION_EXPIRED")
        if inv.paid:
            return d(SKIP, "ALREADY_PAID")
        if inv.cancelled:
            return d(SKIP, "CANCELLED")
        if inv.due_at and time.time() > inv.due_at:
            return d(REFUSE, "INVOICE_EXPIRED")
        if not self.vault.functions.isPayeeAllowed(inv.payee).call():
            return d(REFUSE, "PAYEE_NOT_ALLOWED")
        if inv.amount > m.per_tx_cap:
            return d(REFUSE, "CAP_EXCEEDED")
        if m.day_spent + inv.amount > m.daily_cap:
            return d(REFUSE, "DAILY_CAP_EXCEEDED")
        if m.approval_threshold and inv.amount >= m.approval_threshold:
            return d(ASK_APPROVAL, "ABOVE_APPROVAL_THRESHOLD")
        return d(PAY, "WITHIN_MANDATE")

    # ------------------------------------------------------------------ act

    def simulate_pay(self, invoice_id: int) -> tuple[bool, str]:
        """eth_call first: never spend gas on a call the chain will reject."""
        try:
            self.vault.functions.pay(invoice_id).call({"from": self.agent})
            return True, "ok"
        except Exception as exc:  # noqa: BLE001 - surface the revert reason
            return False, _clean_error(exc)

    def pay(self, invoice_id: int) -> str:
        ok, reason = self.simulate_pay(invoice_id)
        if not ok:
            raise RuntimeError(f"simulation rejected invoice {invoice_id}: {reason}")
        tx = self.vault.functions.pay(invoice_id).build_transaction(self._tx_params())
        signed = self.w3.eth.account.sign_transaction(tx, self.account.key)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(h, timeout=120)
        if receipt.status != 1:
            raise RuntimeError(f"tx reverted: {h.hex()}")
        return h.hex()

    def _tx_params(self) -> dict:
        return {
            "from": self.agent,
            "nonce": self.w3.eth.get_transaction_count(self.agent),
            "chainId": self.w3.eth.chain_id,
            "gas": 500_000,
            "maxFeePerGas": self.w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": self.w3.eth.gas_price,
        }

    # ----------------------------------------------------------------- log

    def log(self, decision: Decision) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(decision.to_json() + "\n")


def _clean_error(exc: Exception) -> str:
    text = str(exc)
    for marker in ("execution reverted:", "revert "):
        if marker in text:
            return text.split(marker, 1)[1].strip().strip("'\"")[:120]
    return text[:120]


def from_env() -> AgentPay:
    """Build an agent from environment variables (see .env.example)."""
    rpc = os.environ.get("RPC_URL", "https://rpc-test.qday.info")
    vault = _require("VAULT_ADDRESS")
    registry = _require("REGISTRY_ADDRESS")
    token = _require("TOKEN_ADDRESS")
    agent_address = _require("AGENT_ADDRESS")
    key = os.environ.get("AGENT_PRIVATE_KEY")

    agent = AgentPay(
        rpc_url=rpc,
        vault=vault,
        agent_address=agent_address,
        private_key=key,
        log_path=os.environ.get("DECISION_LOG", "agent/logs/decisions.jsonl"),
    )
    agent.set_registry(registry)
    agent.token_address = Web3.to_checksum_address(token)
    return agent


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing environment variable {name}")
    return value
