// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {InvoiceRegistry} from "./InvoiceRegistry.sol";
import {PaymentReceipt} from "./PaymentReceipt.sol";

/// @title PolicyVault
/// @notice The only component that holds money. An agent may propose payments; the vault decides
///         whether they are inside the mandate. Caps, allowlist, idempotency, approval threshold,
///         session expiry and the pause switch are all enforced here — never in the agent.
contract PolicyVault is EIP712, Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 public constant DAY = 1 days;

    struct Mandate {
        bool active;
        uint96 perTxCap;
        uint96 dailyCap;
        uint96 approvalThreshold; // 0 = approvals disabled
        uint64 validUntil; // 0 = no expiry
        uint64 dayStart;
        uint96 daySpent;
        uint32 nonce;
    }

    bytes32 public constant APPROVAL_TYPEHASH =
        keccak256("Approval(uint256 invoiceId,uint256 amount,address payee,uint256 nonce,uint256 deadline)");

    IERC20 public immutable token;
    InvoiceRegistry public immutable registry;
    PaymentReceipt public immutable receipts;

    bool public paused;

    mapping(address => Mandate) public mandates;
    mapping(address => bool) public isPayeeAllowed;

    event MandateSet(
        address indexed agent,
        uint96 perTxCap,
        uint96 dailyCap,
        uint96 approvalThreshold,
        uint64 validUntil
    );
    event SessionRevoked(address indexed agent);
    event PayeeAllowed(address indexed payee, bool allowed);
    event Deposited(address indexed from, uint96 amount);
    event Withdrawn(address indexed to, uint96 amount);
    event Paid(uint256 indexed invoiceId, address indexed agent, address indexed payee, uint96 amount);
    event ApprovalUsed(uint256 indexed invoiceId, uint32 nonce);
    event PausedBy(address indexed who);
    event UnpausedBy(address indexed who);

    error VaultPaused();
    error MustBePaused();
    error NotAgent();
    error SessionExpired();
    error PayeeNotAllowed();
    error CapExceeded();
    error DailyCapExceeded();
    error ApprovalRequired();
    error ApprovalExpired();
    error BadApproval();
    error InvoiceExpired();
    error AlreadyPaid();
    error AlreadyCancelled();
    error InsufficientVaultBalance();
    error ZeroAddress();
    error ZeroAmount();

    constructor(IERC20 token_, address owner_)
        EIP712("AgentPay", "1")
        Ownable(owner_)
    {
        if (address(token_) == address(0)) revert ZeroAddress();
        token = token_;
        registry = new InvoiceRegistry(address(this));
        receipts = new PaymentReceipt(address(this));
    }

    // ---------------------------------------------------------------- owner

    /// @notice Grant or replace an agent's session: budget, payee scope and expiry.
    function setMandate(
        address agent,
        uint96 perTxCap,
        uint96 dailyCap,
        uint96 approvalThreshold,
        uint64 validUntil
    ) external onlyOwner {
        if (agent == address(0)) revert ZeroAddress();
        if (perTxCap == 0 || dailyCap == 0) revert ZeroAmount();
        if (perTxCap > dailyCap) revert CapExceeded();

        mandates[agent] = Mandate({
            active: true,
            perTxCap: perTxCap,
            dailyCap: dailyCap,
            approvalThreshold: approvalThreshold,
            validUntil: validUntil,
            dayStart: uint64(block.timestamp),
            daySpent: 0,
            nonce: 0
        });

        emit MandateSet(agent, perTxCap, dailyCap, approvalThreshold, validUntil);
    }

    /// @notice Kill an agent's authority immediately, without touching the pause switch.
    function revokeSession(address agent) external onlyOwner {
        mandates[agent].active = false;
        emit SessionRevoked(agent);
    }

    function setPayeeAllowed(address payee, bool allowed) external onlyOwner {
        if (payee == address(0)) revert ZeroAddress();
        isPayeeAllowed[payee] = allowed;
        emit PayeeAllowed(payee, allowed);
    }

    function deposit(uint96 amount) external onlyOwner {
        if (amount == 0) revert ZeroAmount();
        token.safeTransferFrom(msg.sender, address(this), amount);
        emit Deposited(msg.sender, amount);
    }

    /// @notice Funds can only leave this way while the vault is paused — an incident response,
    ///         not something an agent can trigger.
    function withdraw(uint96 amount) external onlyOwner {
        if (!paused) revert MustBePaused();
        token.safeTransfer(owner(), amount);
        emit Withdrawn(owner(), amount);
    }

    function pause() external onlyOwner {
        paused = true;
        emit PausedBy(msg.sender);
    }

    function unpause() external onlyOwner {
        paused = false;
        emit UnpausedBy(msg.sender);
    }

    // ---------------------------------------------------------------- agent

    function pay(uint256 invoiceId) external nonReentrant {
        _pay(invoiceId, msg.sender, 0, "");
    }

    function payWithApproval(uint256 invoiceId, uint256 deadline, bytes calldata sig)
        external
        nonReentrant
    {
        _pay(invoiceId, msg.sender, deadline, sig);
    }

    function _pay(uint256 invoiceId, address agent, uint256 deadline, bytes memory sig) internal {
        if (paused) revert VaultPaused();

        Mandate storage m = mandates[agent];
        if (!m.active) revert NotAgent();
        if (m.validUntil != 0 && block.timestamp > m.validUntil) revert SessionExpired();

        InvoiceRegistry.Invoice memory inv = registry.getInvoice(invoiceId);
        if (inv.paid) revert AlreadyPaid();
        if (inv.cancelled) revert AlreadyCancelled();
        if (inv.dueAt != 0 && block.timestamp > inv.dueAt) revert InvoiceExpired();
        if (!isPayeeAllowed[inv.payee]) revert PayeeNotAllowed();
        if (inv.amount > m.perTxCap) revert CapExceeded();

        _rollWindow(m);
        if (uint256(m.daySpent) + inv.amount > m.dailyCap) revert DailyCapExceeded();

        if (m.approvalThreshold != 0 && inv.amount >= m.approvalThreshold) {
            _checkApproval(m, invoiceId, inv.amount, inv.payee, deadline, sig);
        }

        // effects before interaction
        m.daySpent = uint96(uint256(m.daySpent) + inv.amount);
        registry.markPaid(invoiceId, agent);

        // interaction
        if (token.balanceOf(address(this)) < inv.amount) revert InsufficientVaultBalance();
        token.safeTransfer(inv.payee, inv.amount);
        receipts.mint(agent, invoiceId, inv.payee, inv.amount);

        emit Paid(invoiceId, agent, inv.payee, inv.amount);
    }

    function _checkApproval(
        Mandate storage m,
        uint256 invoiceId,
        uint96 amount,
        address payee,
        uint256 deadline,
        bytes memory sig
    ) internal {
        if (sig.length == 0) revert ApprovalRequired();
        if (deadline < block.timestamp) revert ApprovalExpired();

        bytes32 structHash =
            keccak256(abi.encode(APPROVAL_TYPEHASH, invoiceId, amount, payee, m.nonce, deadline));
        (address signer, ECDSA.RecoverError err,) = ECDSA.tryRecover(_hashTypedDataV4(structHash), sig);
        if (err != ECDSA.RecoverError.NoError || signer != owner()) revert BadApproval();

        unchecked {
            m.nonce += 1;
        }
        emit ApprovalUsed(invoiceId, m.nonce);
    }

    function _rollWindow(Mandate storage m) internal {
        if (block.timestamp >= uint256(m.dayStart) + DAY) {
            m.dayStart = uint64(block.timestamp);
            m.daySpent = 0;
        }
    }

    // ---------------------------------------------------------------- views

    function mandateOf(address agent) external view returns (Mandate memory) {
        return mandates[agent];
    }

    function remainingToday(address agent) external view returns (uint256) {
        Mandate memory m = mandates[agent];
        if (!m.active) return 0;
        if (block.timestamp >= uint256(m.dayStart) + DAY) return m.dailyCap;
        return m.dailyCap > m.daySpent ? m.dailyCap - m.daySpent : 0;
    }

    function approvalDigest(
        uint256 invoiceId,
        uint256 amount,
        address payee,
        uint256 nonce,
        uint256 deadline
    ) external view returns (bytes32) {
        return _hashTypedDataV4(
            keccak256(abi.encode(APPROVAL_TYPEHASH, invoiceId, amount, payee, nonce, deadline))
        );
    }
}
