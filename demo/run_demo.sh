#!/usr/bin/env bash
# AgentPay — full demo run against a freshly deployed vault.
#
#   ./demo/run_demo.sh            # uses .env (RPC, addresses, keys)
#
# Five beats, in order:
#   1. invoice within the mandate        -> paid, receipt minted
#   2. invoice above the per-tx cap      -> refused CAP_EXCEEDED
#   3. invoice above approval threshold  -> owner signs EIP-712, agent submits
#   4. replay of a paid invoice          -> reverts AlreadyPaid
#   5. vault paused                      -> refused VAULT_PAUSED, then paid after resume

set -euo pipefail
cd "$(dirname "$0")/.."
set -a && . ./.env && set +a
PY=".venv/bin/python"

hr() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

hr "state before"
$PY agent/owner.py state

hr "beat 1 — invoice 0.15 (within 0.30 per-tx cap)"
$PY agent/provider.py --payee "$PAYEE" --amount 0.15 --memo "GPU rental, November" --due-in-hours 48 | head -1
$PY agent/run_agent.py --once

hr "beat 2 — invoice 0.50 (over the per-tx cap)"
$PY agent/provider.py --payee "$PAYEE" --amount 0.50 --memo "annual hosting" | head -1
$PY agent/run_agent.py --once

hr "beat 3 — invoice 0.25 (above the 0.20 approval threshold)"
$PY agent/provider.py --payee "$PAYEE" --amount 0.25 --memo "consulting, November" | head -1
$PY agent/run_agent.py --once            # agent stops and asks
echo "→ owner signs off-chain:"
LAST=$($PY - <<'EOF'
import os, sys
sys.path.insert(0, "agent")
from web3 import Web3
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
reg = w3.eth.contract(address=Web3.to_checksum_address(os.environ["REGISTRY_ADDRESS"]), abi=[{"name":"invoiceCount","type":"function","stateMutability":"view","inputs":[],"outputs":[{"name":"","type":"uint256"}]}])
print(reg.functions.invoiceCount().call())
EOF
)
$PY agent/owner.py approve "$LAST"
$PY agent/run_agent.py --once            # agent submits the signed approval

hr "beat 4 — replay of invoice #1"
set +e
cast send "$VAULT_ADDRESS" "pay(uint256)" 1 \
  --keystore wallets/keystore/agentpay-agent.json --password "${AGENT_KEYSTORE_PASSWORD:-AevumAgent2026}" \
  --rpc-url "$RPC_URL" 2>&1 | grep -iE "revert|AlreadyPaid" | head -2
set -e

hr "beat 5 — kill switch"
$PY agent/owner.py pause | tail -1
$PY agent/provider.py --payee "$PAYEE" --amount 0.15 --memo "support retainer" | head -1
$PY agent/run_agent.py --once            # refused while paused
$PY agent/owner.py unpause | tail -1
$PY agent/run_agent.py --once            # same invoice pays after resume

hr "state after"
$PY agent/owner.py state
