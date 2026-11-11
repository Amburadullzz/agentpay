.PHONY: setup test coverage agent dashboard clean

# One-command setup: contract dependencies + python env
setup:
	forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts@v5.1.0
	uv venv .venv
	uv pip install --python .venv/bin/python web3 pillow gTTS imageio-ffmpeg
	@echo "setup done — copy .env.example to .env and fill in the addresses/keys"

test:
	forge test -vv

coverage:
	forge coverage --report summary

# One pass of the agent against whatever is open on chain
agent:
	@set -a && . ./.env && set +a && .venv/bin/python agent/run_agent.py --once

dashboard:
	cd web && python3 -m http.server 8088

clean:
	forge clean
	rm -rf demo/frames demo/segments demo/audio .venv
