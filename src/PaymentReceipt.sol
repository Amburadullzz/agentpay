// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {Base64} from "@openzeppelin/contracts/utils/Base64.sol";
import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";

/// @title PaymentReceipt
/// @notice Verifiable receipt for a settled invoice. One token per invoice, tokenId == invoiceId,
///         minted by the vault to the paying agent. Metadata lives on-chain: no IPFS, no server.
contract PaymentReceipt is ERC721 {
    struct Receipt {
        address payee;
        uint96 amount;
        uint64 paidAt;
    }

    address public immutable vault;

    mapping(uint256 => Receipt) public receipts;

    error NotVault();

    constructor(address vault_) ERC721("AgentPay Receipt", "APAY-R") {
        vault = vault_;
    }

    function mint(address to, uint256 invoiceId, address payee, uint96 amount) external {
        if (msg.sender != vault) revert NotVault();
        _mint(to, invoiceId);
        receipts[invoiceId] = Receipt({payee: payee, amount: amount, paidAt: uint64(block.timestamp)});
    }

    /// @notice On-chain JSON metadata so a receipt is verifiable without trusting any host.
    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        _requireOwned(tokenId);
        Receipt memory r = receipts[tokenId];

        string memory json = string.concat(
            '{"name":"AgentPay Receipt #',
            Strings.toString(tokenId),
            '","description":"Proof of payment settled through AgentPay on QDay Aevum.",',
            '"attributes":[',
            '{"trait_type":"invoice","value":',
            Strings.toString(tokenId),
            "},",
            '{"trait_type":"payee","value":"',
            Strings.toHexString(r.payee),
            '"},',
            '{"trait_type":"amount_tUSD8","value":"',
            _formatAmount(r.amount),
            '"},',
            '{"trait_type":"paid_at","value":',
            Strings.toString(r.paidAt),
            "}]}"
        );

        return string.concat("data:application/json;base64,", Base64.encode(bytes(json)));
    }

    /// @dev 6-decimal fixed point to a plain decimal string, e.g. 1500000 -> "1.5".
    function _formatAmount(uint96 amount) internal pure returns (string memory) {
        uint256 whole = amount / 1e6;
        uint256 frac = amount % 1e6;
        if (frac == 0) return Strings.toString(whole);

        string memory fracStr = Strings.toString(frac);
        uint256 pad = 6 - bytes(fracStr).length;
        bytes memory zeros = new bytes(pad);
        for (uint256 i = 0; i < pad; i++) {
            zeros[i] = "0";
        }
        // strip trailing zeros of the fractional part
        bytes memory f = bytes(fracStr);
        uint256 end = f.length;
        while (end > 0 && f[end - 1] == "0") {
            end--;
        }
        bytes memory trimmed = new bytes(end);
        for (uint256 i = 0; i < end; i++) {
            trimmed[i] = f[i];
        }
        return string.concat(Strings.toString(whole), ".", string(zeros), string(trimmed));
    }
}
