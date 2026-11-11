// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title InvoiceRegistry
/// @notice On-chain invoices: a provider writes what is owed, the vault is the only
///         address allowed to close an invoice. The registry never moves funds.
contract InvoiceRegistry {
    struct Invoice {
        address issuer; // who created the invoice
        address payee; // who receives the money
        uint96 amount; // in tUSD8 base units (6 decimals)
        bytes32 memoHash; // keccak256 of the human-readable memo
        uint64 dueAt; // unix seconds, 0 = no deadline
        bool paid;
        bool cancelled;
    }

    address public immutable vault;
    uint256 public invoiceCount;

    mapping(uint256 => Invoice) private _invoices;
    mapping(uint256 => address) public paidBy;

    event InvoiceCreated(
        uint256 indexed id,
        address indexed issuer,
        address indexed payee,
        uint96 amount,
        bytes32 memoHash,
        uint64 dueAt
    );
    event InvoiceCancelled(uint256 indexed id);
    event InvoicePaid(uint256 indexed id, address indexed payer, uint96 amount);

    error NotVault();
    error NotIssuer();
    error UnknownInvoice();
    error AlreadyPaid();
    error AlreadyCancelled();
    error ZeroAmount();
    error ZeroAddress();

    modifier onlyVault() {
        if (msg.sender != vault) revert NotVault();
        _;
    }

    constructor(address vault_) {
        if (vault_ == address(0)) revert ZeroAddress();
        vault = vault_;
    }

    /// @notice Issue an invoice. Anyone may issue one; only the vault may settle it.
    function createInvoice(address payee, uint96 amount, bytes32 memoHash, uint64 dueAt)
        external
        returns (uint256 id)
    {
        if (payee == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        unchecked {
            id = ++invoiceCount;
        }
        _invoices[id] = Invoice({
            issuer: msg.sender,
            payee: payee,
            amount: amount,
            memoHash: memoHash,
            dueAt: dueAt,
            paid: false,
            cancelled: false
        });
        emit InvoiceCreated(id, msg.sender, payee, amount, memoHash, dueAt);
    }

    /// @notice Issuer withdraws an unpaid invoice.
    function cancelInvoice(uint256 id) external {
        Invoice storage inv = _invoices[id];
        if (inv.issuer == address(0)) revert UnknownInvoice();
        if (inv.issuer != msg.sender) revert NotIssuer();
        if (inv.paid) revert AlreadyPaid();
        if (inv.cancelled) revert AlreadyCancelled();
        inv.cancelled = true;
        emit InvoiceCancelled(id);
    }

    /// @notice Close an invoice. Vault-only: the component that moved the money is the
    ///         only one allowed to claim a payment happened.
    function markPaid(uint256 id, address payer) external onlyVault {
        Invoice storage inv = _invoices[id];
        if (inv.issuer == address(0)) revert UnknownInvoice();
        if (inv.paid) revert AlreadyPaid();
        if (inv.cancelled) revert AlreadyCancelled();
        inv.paid = true;
        paidBy[id] = payer;
        emit InvoicePaid(id, payer, inv.amount);
    }

    function getInvoice(uint256 id) external view returns (Invoice memory) {
        Invoice memory inv = _invoices[id];
        if (inv.issuer == address(0)) revert UnknownInvoice();
        return inv;
    }

    function exists(uint256 id) external view returns (bool) {
        return _invoices[id].issuer != address(0);
    }
}
