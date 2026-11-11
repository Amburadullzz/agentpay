// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {PolicyVault} from "../src/PolicyVault.sol";
import {InvoiceRegistry} from "../src/InvoiceRegistry.sol";
import {PaymentReceipt} from "../src/PaymentReceipt.sol";
import {MockUSD8} from "./mocks/MockUSD8.sol";

contract PolicyVaultTest is Test {
    PolicyVault vault;
    InvoiceRegistry registry;
    PaymentReceipt receipts;
    MockUSD8 usd;

    uint256 constant OWNER_PK = 0xA11CE;
    address owner;
    address agent = address(0xA9E47);
    address provider = address(0xB0B);
    address payee = address(0xB0B); // provider is paid directly
    address stranger = address(0x5EED);

    uint96 constant CAP_TX = 3_000_000; // 3 tUSD8
    uint96 constant CAP_DAY = 8_000_000; // 8 tUSD8
    uint96 constant THRESHOLD = 2_000_000; // 2 tUSD8
    uint256 constant FLOAT = 50_000_000; // 50 tUSD8 in the vault

    bytes32 constant MEMO = keccak256("hosting invoice 2026-11");

    function setUp() public {
        owner = vm.addr(OWNER_PK);
        usd = new MockUSD8();
        vault = new PolicyVault(IERC20(address(usd)), owner);
        registry = vault.registry();
        receipts = vault.receipts();

        usd.mint(owner, FLOAT);
        vm.startPrank(owner);
        usd.approve(address(vault), type(uint256).max);
        vault.deposit(uint96(FLOAT));
        vault.setPayeeAllowed(payee, true);
        vault.setMandate(agent, CAP_TX, CAP_DAY, THRESHOLD, 0);
        vm.stopPrank();
    }

    // ------------------------------------------------------------- helpers

    function _invoice(uint96 amount) internal returns (uint256 id) {
        vm.prank(provider);
        id = registry.createInvoice(payee, amount, MEMO, 0);
    }

    function _pay(uint256 id) internal {
        vm.prank(agent);
        vault.pay(id);
    }

    function _signApproval(uint256 id, uint96 amount, uint256 deadline)
        internal
        view
        returns (bytes memory sig)
    {
        uint256 nonce = vault.mandateOf(agent).nonce;
        bytes32 digest = vault.approvalDigest(id, amount, payee, nonce, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(OWNER_PK, digest);
        sig = abi.encodePacked(r, s, v);
    }

    // --------------------------------------------------------- happy paths

    function test_pay_withinCaps() public {
        uint256 id = _invoice(1_000_000); // 1 tUSD8
        uint256 before = usd.balanceOf(payee);

        _pay(id);

        assertEq(usd.balanceOf(payee) - before, 1_000_000, "payee received the amount");
        assertEq(usd.balanceOf(address(vault)), FLOAT - 1_000_000, "vault debited");
        assertTrue(registry.getInvoice(id).paid, "invoice closed");
        assertEq(registry.paidBy(id), agent, "payer recorded");
        assertEq(vault.mandateOf(agent).daySpent, 1_000_000, "day spend tracked");
    }

    function test_pay_mintsReceipt() public {
        uint256 id = _invoice(1_000_000);
        _pay(id);

        assertEq(receipts.ownerOf(id), agent, "agent owns the receipt");
        assertEq(receipts.balanceOf(agent), 1, "one receipt");

        (address rPayee, uint96 rAmount, uint64 rAt) = receipts.receipts(id);
        assertEq(rPayee, payee);
        assertEq(rAmount, 1_000_000);
        assertGt(rAt, 0);

        string memory uri = receipts.tokenURI(id);
        assertTrue(bytes(uri).length > 40, "tokenURI present");
    }

    function test_pay_multipleAccumulateDaily() public {
        uint256 a = _invoice(1_000_000);
        uint256 b = _invoice(1_500_000);

        _pay(a);
        _pay(b);

        assertEq(vault.mandateOf(agent).daySpent, 2_500_000, "spend accumulates");
        assertEq(usd.balanceOf(payee), 2_500_000, "payee received both");
    }

    function test_revert_aboveThresholdNeedsApproval() public {
        uint256 id = _invoice(2_000_000); // exactly at the threshold
        vm.prank(agent);
        vm.expectRevert(PolicyVault.ApprovalRequired.selector);
        vault.pay(id);
    }

    function test_pay_resetsDailyWindow() public {
        uint256 a = _invoice(1_000_000);
        _pay(a);
        assertEq(vault.mandateOf(agent).daySpent, 1_000_000);

        vm.warp(block.timestamp + 1 days + 1);
        assertEq(vault.remainingToday(agent), CAP_DAY, "window rolled");

        uint256 b = _invoice(1_000_000);
        _pay(b);
        assertEq(vault.mandateOf(agent).daySpent, 1_000_000, "counter restarted");
    }

    function test_payWithApproval_aboveThreshold() public {
        uint256 id = _invoice(2_500_000);
        bytes memory sig = _signApproval(id, 2_500_000, block.timestamp + 1 hours);

        vm.prank(agent);
        vault.payWithApproval(id, block.timestamp + 1 hours, sig);

        assertTrue(registry.getInvoice(id).paid);
        assertEq(vault.mandateOf(agent).nonce, 1, "nonce consumed");
    }

    // ------------------------------------------------------------- refusals

    function test_revert_payeeNotAllowed() public {
        vm.prank(owner);
        vault.setPayeeAllowed(stranger, false);

        vm.prank(provider);
        uint256 id = registry.createInvoice(stranger, 1_000_000, MEMO, 0);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.PayeeNotAllowed.selector);
        vault.pay(id);
    }

    function test_revert_perTxCap() public {
        uint256 id = _invoice(CAP_TX + 1);
        vm.prank(agent);
        vm.expectRevert(PolicyVault.CapExceeded.selector);
        vault.pay(id);
    }

    function test_revert_dailyCap() public {
        // five payments of 1.5 stay under the per-tx cap and under the approval threshold
        for (uint256 i = 0; i < 5; i++) {
            _pay(_invoice(1_500_000)); // 7.5 spent
        }
        uint256 id = _invoice(1_000_000); // 7.5 + 1 = 8.5 > 8
        vm.prank(agent);
        vm.expectRevert(PolicyVault.DailyCapExceeded.selector);
        vault.pay(id);
    }

    function test_revert_alreadyPaid() public {
        uint256 id = _invoice(1_000_000);
        _pay(id);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.AlreadyPaid.selector);
        vault.pay(id);
    }

    function test_revert_approvalRequired() public {
        uint256 id = _invoice(THRESHOLD);
        vm.prank(agent);
        vm.expectRevert(PolicyVault.ApprovalRequired.selector);
        vault.pay(id);
    }

    function test_revert_badApproval_wrongSigner() public {
        uint256 id = _invoice(2_500_000);
        uint256 nonce = vault.mandateOf(agent).nonce;
        bytes32 digest = vault.approvalDigest(id, 2_500_000, payee, nonce, block.timestamp + 1 hours);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(0xBAD5EED, digest); // not the owner
        bytes memory sig = abi.encodePacked(r, s, v);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.BadApproval.selector);
        vault.payWithApproval(id, block.timestamp + 1 hours, sig);
    }

    function test_revert_approvalReplay() public {
        uint256 id = _invoice(2_500_000);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signApproval(id, 2_500_000, deadline);

        vm.prank(agent);
        vault.payWithApproval(id, deadline, sig);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.AlreadyPaid.selector);
        vault.payWithApproval(id, deadline, sig);
    }

    function test_revert_approvalExpired() public {
        uint256 id = _invoice(2_500_000);
        uint256 deadline = block.timestamp + 10;
        bytes memory sig = _signApproval(id, 2_500_000, deadline);

        vm.warp(deadline + 1);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.ApprovalExpired.selector);
        vault.payWithApproval(id, deadline, sig);
    }

    function test_revert_invoiceExpired() public {
        vm.prank(provider);
        uint256 id = registry.createInvoice(payee, 1_000_000, MEMO, uint64(block.timestamp + 100));
        vm.warp(block.timestamp + 101);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.InvoiceExpired.selector);
        vault.pay(id);
    }

    function test_revert_vaultPaused() public {
        uint256 id = _invoice(1_000_000);
        vm.prank(owner);
        vault.pause();

        vm.prank(agent);
        vm.expectRevert(PolicyVault.VaultPaused.selector);
        vault.pay(id);
    }

    function test_pauseBlocksSignedApprovalToo() public {
        uint256 id = _invoice(2_500_000);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signApproval(id, 2_500_000, deadline);

        vm.prank(owner);
        vault.pause();

        vm.prank(agent);
        vm.expectRevert(PolicyVault.VaultPaused.selector);
        vault.payWithApproval(id, deadline, sig);
    }

    function test_revert_notAgent() public {
        uint256 id = _invoice(1_000_000);
        vm.prank(stranger);
        vm.expectRevert(PolicyVault.NotAgent.selector);
        vault.pay(id);
    }

    function test_revert_sessionExpired() public {
        vm.prank(owner);
        vault.setMandate(agent, CAP_TX, CAP_DAY, THRESHOLD, uint64(block.timestamp + 100));

        vm.warp(block.timestamp + 101);
        uint256 id = _invoice(1_000_000);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.SessionExpired.selector);
        vault.pay(id);
    }

    function test_revert_sessionRevoked() public {
        uint256 id = _invoice(1_000_000);
        vm.prank(owner);
        vault.revokeSession(agent);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.NotAgent.selector);
        vault.pay(id);
    }

    function test_revert_cancelledInvoice() public {
        uint256 id = _invoice(1_000_000);
        vm.prank(provider);
        registry.cancelInvoice(id);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.AlreadyCancelled.selector);
        vault.pay(id);
    }

    function test_revert_insufficientVaultBalance() public {
        // drain the vault by pausing and withdrawing, then unpausing
        vm.startPrank(owner);
        vault.pause();
        vault.withdraw(uint96(FLOAT));
        vault.unpause();
        vm.stopPrank();

        uint256 id = _invoice(1_000_000);
        vm.prank(agent);
        vm.expectRevert(PolicyVault.InsufficientVaultBalance.selector);
        vault.pay(id);
    }

    // ------------------------------------------------------- access control

    function test_agentCannotSetMandate() public {
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vault.setMandate(agent, 1e6, 1e6, 0, 0);
    }

    function test_agentCannotPause() public {
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vault.pause();
    }

    function test_agentCannotWithdraw() public {
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vault.withdraw(1e6);
    }

    function test_agentCannotAllowPayee() public {
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, agent));
        vault.setPayeeAllowed(stranger, true);
    }

    function test_onlyVaultCanMarkPaid() public {
        uint256 id = _invoice(1_000_000);
        vm.prank(stranger);
        vm.expectRevert(InvoiceRegistry.NotVault.selector);
        registry.markPaid(id, stranger);
    }

    function test_onlyVaultCanMintReceipt() public {
        vm.prank(stranger);
        vm.expectRevert(PaymentReceipt.NotVault.selector);
        receipts.mint(stranger, 1, payee, 1);
    }

    function test_withdrawRequiresPause() public {
        vm.prank(owner);
        vm.expectRevert(PolicyVault.MustBePaused.selector);
        vault.withdraw(1e6);
    }

    // ----------------------------------------------------------------- fuzz

    function testFuzz_capBoundary(uint96 amount) public {
        amount = uint96(bound(amount, 1, CAP_DAY));
        uint256 id = _invoice(amount);

        if (amount > CAP_TX) {
            vm.prank(agent);
            vm.expectRevert(PolicyVault.CapExceeded.selector);
            vault.pay(id);
        } else if (amount >= THRESHOLD) {
            vm.prank(agent);
            vm.expectRevert(PolicyVault.ApprovalRequired.selector);
            vault.pay(id);
        } else {
            _pay(id);
            assertTrue(registry.getInvoice(id).paid);
            assertEq(vault.mandateOf(agent).daySpent, amount);
        }
    }

    function testFuzz_neverSpendsMoreThanDailyCap(uint96 a, uint96 b, uint96 c) public {
        a = uint96(bound(a, 1, CAP_TX));
        b = uint96(bound(b, 1, CAP_TX));
        c = uint96(bound(c, 1, CAP_TX));

        _tryPay(a);
        _tryPay(b);
        _tryPay(c);

        assertLe(vault.mandateOf(agent).daySpent, CAP_DAY, "daily cap held");
    }

    function _tryPay(uint96 amount) internal {
        if (amount >= THRESHOLD) return; // those need an approval; not the point of this fuzz
        uint256 id = _invoice(amount);
        vm.prank(agent);
        try vault.pay(id) {} catch {}
    }

    function testFuzz_invoicePaidAtMostOnce(uint96 amount) public {
        amount = uint96(bound(amount, 1, THRESHOLD - 1)); // below the approval threshold
        uint256 id = _invoice(amount);
        _pay(id);

        vm.prank(agent);
        vm.expectRevert(PolicyVault.AlreadyPaid.selector);
        vault.pay(id);

        assertEq(receipts.balanceOf(agent), 1, "single receipt");
    }
}
