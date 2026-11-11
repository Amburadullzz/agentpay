// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {PolicyVault} from "../src/PolicyVault.sol";
import {InvoiceRegistry} from "../src/InvoiceRegistry.sol";
import {PaymentReceipt} from "../src/PaymentReceipt.sol";
import {MockUSD8} from "./mocks/MockUSD8.sol";

/// @notice Edge cases for the registry, the receipt metadata and the vault's owner surface.
contract ComponentsTest is Test {
    PolicyVault vault;
    InvoiceRegistry registry;
    PaymentReceipt receipts;
    MockUSD8 usd;

    address owner = address(0x0FF1CE);
    address agent = address(0xA9E47);
    address provider = address(0xB0B);
    address stranger = address(0x5EED);

    bytes32 constant MEMO = keccak256("memo");

    function setUp() public {
        usd = new MockUSD8();
        vault = new PolicyVault(IERC20(address(usd)), owner);
        registry = vault.registry();
        receipts = vault.receipts();

        usd.mint(owner, 100e6);
        vm.startPrank(owner);
        usd.approve(address(vault), type(uint256).max);
        vault.deposit(10e6);
        vault.setPayeeAllowed(provider, true);
        vault.setMandate(agent, 3e6, 8e6, 2e6, 0);
        vm.stopPrank();
    }

    // ------------------------------------------------------- registry edges

    function test_createInvoice_revertsOnZeroPayee() public {
        vm.prank(provider);
        vm.expectRevert(InvoiceRegistry.ZeroAddress.selector);
        registry.createInvoice(address(0), 1e6, MEMO, 0);
    }

    function test_createInvoice_revertsOnZeroAmount() public {
        vm.prank(provider);
        vm.expectRevert(InvoiceRegistry.ZeroAmount.selector);
        registry.createInvoice(provider, 0, MEMO, 0);
    }

    function test_cancel_revertsForNonIssuer() public {
        vm.prank(provider);
        uint256 id = registry.createInvoice(provider, 1e6, MEMO, 0);

        vm.prank(stranger);
        vm.expectRevert(InvoiceRegistry.NotIssuer.selector);
        registry.cancelInvoice(id);
    }

    function test_cancel_twiceReverts() public {
        vm.startPrank(provider);
        uint256 id = registry.createInvoice(provider, 1e6, MEMO, 0);
        registry.cancelInvoice(id);
        vm.expectRevert(InvoiceRegistry.AlreadyCancelled.selector);
        registry.cancelInvoice(id);
        vm.stopPrank();
    }

    function test_cancel_revertsAfterPayment() public {
        vm.prank(provider);
        uint256 id = registry.createInvoice(provider, 1e6, MEMO, 0);
        vm.prank(agent);
        vault.pay(id);

        vm.prank(provider);
        vm.expectRevert(InvoiceRegistry.AlreadyPaid.selector);
        registry.cancelInvoice(id);
    }

    function test_getInvoice_revertsWhenUnknown() public {
        vm.expectRevert(InvoiceRegistry.UnknownInvoice.selector);
        registry.getInvoice(999);
    }

    function test_markPaid_revertsWhenUnknown() public {
        vm.prank(address(vault));
        vm.expectRevert(InvoiceRegistry.UnknownInvoice.selector);
        registry.markPaid(999, agent);
    }

    function test_exists() public {
        assertFalse(registry.exists(1));
        vm.prank(provider);
        registry.createInvoice(provider, 1e6, MEMO, 0);
        assertTrue(registry.exists(1));
    }

    function test_createInvoice_emitsEvent() public {
        vm.expectEmit(true, true, true, true);
        emit InvoiceRegistry.InvoiceCreated(1, provider, provider, 1e6, MEMO, 0);
        vm.prank(provider);
        registry.createInvoice(provider, 1e6, MEMO, 0);
    }

    // -------------------------------------------------------- receipt edges

    function _payAmount(uint96 amount) internal returns (uint256 id) {
        vm.prank(provider);
        id = registry.createInvoice(provider, amount, MEMO, 0);
        vm.prank(agent);
        vault.pay(id);
    }

    function test_tokenUri_wholeNumber() public {
        uint256 id = _payAmount(1_000_000); // 1.0
        string memory uri = receipts.tokenURI(id);
        assertTrue(bytes(uri).length > 0);
    }

    function test_tokenUri_fractionalTrimsZeros() public {
        uint256 id = _payAmount(1_500_000); // 1.5
        string memory uri = receipts.tokenURI(id);
        assertTrue(bytes(uri).length > 0);
    }

    function test_tokenUri_smallFraction() public {
        uint256 id = _payAmount(1); // 0.000001
        string memory uri = receipts.tokenURI(id);
        assertTrue(bytes(uri).length > 0);
    }

    function test_tokenUri_revertsForUnknownToken() public {
        vm.expectRevert();
        receipts.tokenURI(42);
    }

    function test_receipt_cannotBeMintedTwice() public {
        uint256 id = _payAmount(1_000_000);
        vm.prank(address(vault));
        vm.expectRevert();
        receipts.mint(agent, id, provider, 1_000_000);
    }

    function test_receipt_isTransferable() public {
        uint256 id = _payAmount(1_000_000);
        vm.prank(agent);
        receipts.transferFrom(agent, stranger, id);
        assertEq(receipts.ownerOf(id), stranger);
    }

    // ------------------------------------------------------ vault owner ops

    function test_setMandate_revertsOnZeroAgent() public {
        vm.prank(owner);
        vm.expectRevert(PolicyVault.ZeroAddress.selector);
        vault.setMandate(address(0), 1e6, 1e6, 0, 0);
    }

    function test_setMandate_revertsOnZeroCaps() public {
        vm.startPrank(owner);
        vm.expectRevert(PolicyVault.ZeroAmount.selector);
        vault.setMandate(agent, 0, 1e6, 0, 0);
        vm.expectRevert(PolicyVault.ZeroAmount.selector);
        vault.setMandate(agent, 1e6, 0, 0, 0);
        vm.stopPrank();
    }

    function test_setMandate_revertsWhenPerTxExceedsDaily() public {
        vm.prank(owner);
        vm.expectRevert(PolicyVault.CapExceeded.selector);
        vault.setMandate(agent, 5e6, 4e6, 0, 0);
    }

    function test_setMandate_resetsSpendAndNonce() public {
        _payAmount(1_000_000);
        assertEq(vault.mandateOf(agent).daySpent, 1_000_000);

        vm.prank(owner);
        vault.setMandate(agent, 3e6, 8e6, 2e6, 0);

        assertEq(vault.mandateOf(agent).daySpent, 0, "budget reset");
        assertEq(vault.mandateOf(agent).nonce, 0, "approval nonce reset");
    }

    function test_deposit_revertsOnZero() public {
        vm.prank(owner);
        vm.expectRevert(PolicyVault.ZeroAmount.selector);
        vault.deposit(0);
    }

    function test_withdraw_returnsFundsToOwner() public {
        uint256 before = usd.balanceOf(owner);
        vm.startPrank(owner);
        vault.pause();
        vault.withdraw(4e6);
        vm.stopPrank();
        assertEq(usd.balanceOf(owner) - before, 4e6);
        assertEq(usd.balanceOf(address(vault)), 6e6);
    }

    function test_revokeThenReMandate_restoresSession() public {
        vm.prank(owner);
        vault.revokeSession(agent);
        assertFalse(vault.mandateOf(agent).active);

        vm.prank(owner);
        vault.setMandate(agent, 3e6, 8e6, 2e6, 0);
        assertTrue(vault.mandateOf(agent).active);

        _payAmount(1_000_000);
        assertTrue(registry.getInvoice(1).paid);
    }

    function test_remainingToday_reportsFullBudgetAfterRoll() public {
        _payAmount(1_000_000);
        assertEq(vault.remainingToday(agent), 7e6);
        vm.warp(block.timestamp + 1 days + 1);
        assertEq(vault.remainingToday(agent), 8e6);
    }

    function test_remainingToday_isZeroWithoutSession() public view {
        assertEq(vault.remainingToday(stranger), 0);
    }

    function test_approvalThresholdZero_meansNoApprovalNeeded() public {
        vm.prank(owner);
        vault.setMandate(agent, 3e6, 8e6, 0, 0); // approvals disabled

        vm.prank(provider);
        uint256 id = registry.createInvoice(provider, 2_500_000, MEMO, 0);

        vm.prank(agent);
        vault.pay(id);
        assertTrue(registry.getInvoice(id).paid);
    }
}
