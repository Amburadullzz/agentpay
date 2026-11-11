# Evidence — AgentPay on QDay Aevum Testnet

Everything below is verifiable on the public explorer. Generated from the agent's own decision log.

## Deployment

- Chain: **44005** (QDay Aevum Testnet), gas 1 gwei
- Deploy tx: [0x76ea4874dd2708a8…](https://explorer-test.qday.info/tx/0x76ea4874dd2708a85c53dbe399bf3436bd8b1739818b7132b7fd225f399b3713)
- PolicyVault: [`0x3438513Ca98021c976D07D4584Ea6742eF2E5B22`](https://explorer-test.qday.info/address/0x3438513Ca98021c976D07D4584Ea6742eF2E5B22)
- InvoiceRegistry: [`0x8F4Fd4Df4e77DaC2BEdA80Aa7193322D658401C8`](https://explorer-test.qday.info/address/0x8F4Fd4Df4e77DaC2BEdA80Aa7193322D658401C8)
- PaymentReceipt (ERC-721): [`0x4bf8b703715e8BC777e3D51D9B20d4C09c07981a`](https://explorer-test.qday.info/address/0x4bf8b703715e8BC777e3D51D9B20d4C09c07981a)

## Participants

- Agent (no owner rights): `0x466895bBD324A28e6271C1d7CC0E877a7659aF89`
- Owner (mandate, approvals, pause): `0xEb20E349d5CBDa98AA8EBf1500390b96F7535B6b`
- Provider / payee: `0xa2adf8680973f201a6Ea56b0eDebB567E89326CB`

## Agent decisions (verbatim log)

| # | Invoice | Amount | Decision | Reason | Transaction |
| --- | --- | --- | --- | --- | --- |
| 1 | #1 | 0.15 tUSD8 | PAY | `PAID` | [de15f952de2c…](https://explorer-test.qday.info/tx/de15f952de2c60f1a14343c89849d1ca3413bbe0d77dc180f4ddd1cf38fec817) |
| 2 | #2 | 0.50 tUSD8 | REFUSE | `CAP_EXCEEDED` | — |
| 3 | #3 | 0.25 tUSD8 | ASK_APPROVAL | `AWAITING_OWNER_SIGNATURE` | — |
| 4 | #2 | 0.50 tUSD8 | REFUSE | `CAP_EXCEEDED` | — |
| 5 | #3 | 0.25 tUSD8 | ASK_APPROVAL | `PAID_WITH_APPROVAL` | [c83f93380478…](https://explorer-test.qday.info/tx/c83f933804788bfe374624d379119758879ef23adab153c89792f6140c6f6d78) |
| 6 | #2 | 0.50 tUSD8 | REFUSE | `CAP_EXCEEDED` | — |
| 7 | #4 | 0.15 tUSD8 | PAY | `PAID` | [f94a7b89c643…](https://explorer-test.qday.info/tx/f94a7b89c64356446afaa292370df8f02a07cd8660620c930d9bf5a94d57e36f) |
| 8 | #2 | 0.50 tUSD8 | REFUSE | `CAP_EXCEEDED` | — |
| 9 | #2 | 0.50 tUSD8 | REFUSE | `VAULT_PAUSED` | — |
| 10 | #5 | 0.15 tUSD8 | REFUSE | `VAULT_PAUSED` | — |
| 11 | #2 | 0.50 tUSD8 | REFUSE | `CAP_EXCEEDED` | — |
| 12 | #5 | 0.15 tUSD8 | PAY | `PAID` | [3ca762a9cd60…](https://explorer-test.qday.info/tx/3ca762a9cd600b963cdf7285ca026c78f0148989368d5bb2d3021ce92cfc60ed) |

## What the log shows

- Invoice #1 (0.15) was inside the mandate and paid; the vault minted receipt #1 to the agent.
- Invoice #2 (0.50) exceeded the 0.30 per-transaction cap and stayed **unpaid** — the agent refused it on every pass, including after the vault was resumed.
- Invoice #3 (0.25) crossed the 0.20 approval threshold: the agent stopped, the owner signed an EIP-712 approval, and the payment landed with the nonce consumed.
- Replaying invoice #1 reverts with `AlreadyPaid` (see the refusal row).
- With the vault paused, invoice #5 was refused `VAULT_PAUSED`; the same invoice paid immediately after `unpause`.

## Receipts

Each paid invoice minted an ERC-721 receipt (tokenId = invoiceId) with on-chain metadata:

- Receipt contract: [`0x4bf8b703715e8BC777e3D51D9B20d4C09c07981a`](https://explorer-test.qday.info/address/0x4bf8b703715e8BC777e3D51D9B20d4C09c07981a)
- Example `tokenURI(1)` decodes to:

```json
{
  "name": "AgentPay Receipt #1",
  "description": "Proof of payment settled through AgentPay on QDay Aevum.",
  "attributes": [
    {
      "trait_type": "invoice",
      "value": 1
    },
    {
      "trait_type": "payee",
      "value": "0xa2adf8680973f201a6ea56b0edebb567e89326cb"
    },
    {
      "trait_type": "amount_tUSD8",
      "value": "0.15"
    }
  ]
}
```

## Test suite

`forge test` → **32 passed, 0 failed** (includes fuzz tests over cap boundaries, replay paths and access control).
