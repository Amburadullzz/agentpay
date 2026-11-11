#!/usr/bin/env bash
# AgentPay — replay the five demo beats, optionally against a freshly deployed vault.
#
#   ./demo/run_demo.sh            # use the deployment in .env
#   ./demo/run_demo.sh --fresh    # deploy a new vault, fund it, then run the beats
#
# Requirements for --fresh: the agent wallet needs tQDAY for gas, the owner wallet needs
# tUSD8 for the vault float (0.55 covers the five beats).
#
# Beats:
#   1. invoice within the mandate        -> paid, receipt minted
#   2. invoice above the per-tx cap      -> refused CAP_EXCEEDED
#   3. invoice above approval threshold  -> owner signs EIP-712, agent submits
#   4. replay of a paid invoice          -> AlreadyPaid
#   5. vault paused                      -> refused VAULT_PAUSED, then paid after resume

set -euo pipefail
cd "$(dirname "$0")/.."
set -a && . ./.env && set +a

PY=".venv/bin/python"
FRESH=0
[ "${1:-}" = "--fresh" ] && FRESH=1

hr() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

if [ "$FRESH" = "1" ]; then
  hr "deploying a fresh vault"
  OWNER_ADDR=$(cast wallet address --private-key "$OWNER_PRIVATE_KEY")
  OUT=$(forge create src/PolicyVault.sol:PolicyVault \
        --rpc-url "$RPC_URL" \
        --private-key "$AGENT_PRIVATE_KEY" \
        --broadcast \
        --constructor-args "$TOKEN_ADDRESS" "$OWNER_ADDR" 2>&1)
  NEW_VAULT=$(echo "$OUT" | awk '/Deployed to:/ {print $3}')
  [ -n "$NEW_VAULT" ] || { echo "$OUT"; exit 1; }
  export VAULT_ADDRESS="$NEW_VAULT"
  export REGISTRY_ADDRESS=$(cast call "$NEW_VAULT" "registry()(address)" --rpc-url "$RPC_URL")
  echo "vault    $NEW_VAULT"
  echo "registry $REGISTRY_ADDRESS"

  hr "funding and configuring the mandate"
  $PY - <<'EOF'
import os
from eth_account import Account
from web3 import Web3

w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"], request_kwargs={"timeout": 60}))
owner = Account.from_key(os.environ["OWNER_PRIVATE_KEY"])
vault_addr = Web3.to_checksum_address(os.environ["VAULT_ADDRESS"])
token_addr = Web3.to_checksum_address(os.environ["TOKEN_ADDRESS"])
agent = Web3.to_checksum_address(os.environ["AGENT_ADDRESS"])
provider = Account.from_key(os.environ["PROVIDER_PRIVATE_KEY"]).address

VAULT = [
    {"name": "deposit", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "a", "type": "uint96"}], "outputs": []},
    {"name": "setPayeeAllowed", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "p", "type": "address"}, {"name": "ok", "type": "bool"}], "outputs": []},
    {"name": "setMandate", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "a", "type": "address"}, {"name": "tx", "type": "uint96"}, {"name": "day", "type": "uint96"},
                {"name": "thr", "type": "uint96"}, {"name": "until", "type": "uint64"}], "outputs": []},
]
TOKEN = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "outputs": [{"name": "", "type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
]

vault = w3.eth.contract(address=vault_addr, abi=VAULT)
token = w3.eth.contract(address=token_addr, abi=TOKEN)

DEPOSIT = 550_000  # 0.55 tUSD8 covers the five beats
bal = token.functions.balanceOf(owner.address).call()
if bal < DEPOSIT:
    raise SystemExit(f"owner wallet has {bal/1e6} tUSD8, needs {DEPOSIT/1e6} — claim at faucet.qday.info")

def send(fn):
    tx = fn.build_transaction({
        "from": owner.address, "nonce": w3.eth.get_transaction_count(owner.address, "pending"),
        "chainId": w3.eth.chain_id, "gas": 300_000,
        "maxFeePerGas": w3.eth.gas_price * 2, "maxPriorityFeePerGas": w3.eth.gas_price,
    })
    signed = w3.eth.account.sign_transaction(tx, owner.key)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    if w3.eth.wait_for_transaction_receipt(h, timeout=180).status != 1:
        raise SystemExit(f"tx reverted: {h.hex()}")

send(token.functions.approve(vault_addr, DEPOSIT))
send(vault.functions.deposit(DEPOSIT))
send(vault.functions.setPayeeAllowed(provider, True))
send(vault.functions.setMandate(agent, 300_000, 800_000, 200_000, 0))
print(f"deposited {DEPOSIT/1e6} tUSD8 · allowlisted {provider} · mandate 0.3/tx, 0.8/day, approval above 0.2")
EOF
fi

PAYEE="${PAYEE:-$($PY -c 'import os; from eth_account import Account; print(Account.from_key(os.environ["PROVIDER_PRIVATE_KEY"]).address)')}"

invoice_count() {
  $PY - <<'EOF'
import os
from web3 import Web3
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"], request_kwargs={"timeout": 30}))
abi = [{"name": "invoiceCount", "type": "function", "stateMutability": "view",
        "inputs": [], "outputs": [{"name": "", "type": "uint256"}]}]
reg = w3.eth.contract(address=Web3.to_checksum_address(os.environ["REGISTRY_ADDRESS"]), abi=abi)
print(reg.functions.invoiceCount().call())
EOF
}

issue() { $PY agent/provider.py --payee "$PAYEE" --amount "$1" --memo "$2" | head -1; }

hr "state before"
$PY agent/owner.py state

hr "beat 1 — invoice 0.15 (within the 0.30 per-tx cap)"
issue 0.15 "GPU rental, November"
$PY agent/run_agent.py --once

hr "beat 2 — invoice 0.50 (over the per-tx cap)"
issue 0.50 "annual hosting"
$PY agent/run_agent.py --once

hr "beat 3 — invoice 0.25 (above the 0.20 approval threshold)"
issue 0.25 "consulting, November"
$PY agent/run_agent.py --once            # the agent stops and asks
ID=$(invoice_count)
echo "→ owner signs off-chain, then the agent submits:"
$PY agent/owner.py approve "$ID" | head -2
$PY agent/run_agent.py --once

hr "beat 4 — replay of a paid invoice"
$PY - <<'EOF'
import sys
sys.path.insert(0, "agent")
from agentpay import from_env

agent = from_env()
ok, reason = agent.simulate_pay(1)
print("replay #1 ->", "UNEXPECTED: still payable" if ok else f"reverted: {reason}")
EOF

hr "beat 5 — kill switch"
$PY agent/owner.py pause | tail -1
issue 0.15 "support retainer"
$PY agent/run_agent.py --once            # refused while paused
$PY agent/owner.py unpause | tail -1
$PY agent/run_agent.py --once            # the same invoice pays after resume

hr "attacks against the same vault"
$PY agent/attack_sim.py || true

hr "state after"
$PY agent/owner.py state
