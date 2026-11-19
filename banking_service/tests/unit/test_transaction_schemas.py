"""Unit tests for Transaction, Transfer, and Balance schema rupee conversions."""
from datetime import datetime, timezone

from app.schemas.account import BalanceResponse
from app.schemas.admin import AdminTransactionResponse
from app.schemas.transaction import TransactionResponse
from app.schemas.transfer import LimitsResponse, PrepareTransferResponse, TransferDetailResponse


def test_transaction_response_rupee_conversions() -> None:
    """Ensure TransactionResponse computed fields convert paise to rupees accurately."""
    now = datetime.now(timezone.utc)
    txn = TransactionResponse(
        id="txn-001",
        reference="TXN202611190001",
        type="TRANSFER",
        amount_minor=500000,
        fee_minor=1500,
        total_debit_minor=501500,
        currency="INR",
        status="COMPLETED",
        channel="IMPS",
        created_at=now,
    )
    dumped = txn.model_dump()

    # Numeric conversions
    assert txn.amount == 5000.0
    assert txn.amount_rupees == 5000.0
    assert txn.fee_rupees == 15.0
    assert txn.total_debit == 5015.0
    assert txn.total_debit_rupees == 5015.0

    # String formatted conversions
    assert txn.amount_formatted == "₹5,000.00"
    assert txn.total_debit_formatted == "₹5,015.00"

    # Serialized dictionary contains rupee fields
    assert dumped["amount"] == 5000.0
    assert dumped["amount_rupees"] == 5000.0
    assert dumped["amount_formatted"] == "₹5,000.00"
    assert dumped["fee_rupees"] == 15.0
    assert dumped["total_debit_rupees"] == 5015.0
    assert dumped["total_debit_formatted"] == "₹5,015.00"


def test_prepare_transfer_response_rupee_conversions() -> None:
    """Ensure PrepareTransferResponse computed fields convert amounts and balances."""
    now = datetime.now(timezone.utc)
    prep = PrepareTransferResponse(
        id="prep-001",
        reference="TXNPREP123",
        status="PENDING_APPROVAL",
        beneficiary={"id": "b-1", "name": "Amit Sharma"},
        amount_minor=500000,
        fee_minor=0,
        total_debit_minor=500000,
        currency="INR",
        available_balance_after_minor=4500000,
        summary_hash="hash123",
        expires_at=now,
    )
    dumped = prep.model_dump()

    assert prep.amount == 5000.0
    assert prep.amount_rupees == 5000.0
    assert prep.amount_formatted == "₹5,000.00"
    assert prep.fee_rupees == 0.0
    assert prep.available_balance_after_rupees == 45000.0
    assert prep.available_balance_after_formatted == "₹45,000.00"
    assert dumped["amount_rupees"] == 5000.0
    assert dumped["available_balance_after_rupees"] == 45000.0


def test_transfer_detail_response_rupee_conversions() -> None:
    """Ensure TransferDetailResponse computed fields convert accurately."""
    now = datetime.now(timezone.utc)
    detail = TransferDetailResponse(
        id="detail-001",
        reference="TXNDET123",
        status="COMPLETED",
        amount_minor=500000,
        fee_minor=0,
        total_debit_minor=500000,
        currency="INR",
        channel="IMPS",
        created_at=now,
    )
    dumped = detail.model_dump()

    assert detail.amount == 5000.0
    assert detail.amount_rupees == 5000.0
    assert detail.amount_formatted == "₹5,000.00"
    assert dumped["amount_rupees"] == 5000.0


def test_limits_response_rupee_conversions() -> None:
    """Ensure LimitsResponse computed fields convert limits from paise to rupees."""
    limits = LimitsResponse(
        per_transaction_limit_minor=10000000,
        daily_limit_minor=50000000,
        daily_used_minor=500000,
        daily_remaining_minor=49500000,
        currency="INR",
    )
    dumped = limits.model_dump()

    assert limits.per_transaction_limit_rupees == 100000.0
    assert limits.daily_limit_rupees == 500000.0
    assert limits.daily_used_rupees == 5000.0
    assert limits.daily_remaining_rupees == 495000.0
    assert dumped["daily_remaining_rupees"] == 495000.0


def test_admin_transaction_response_rupee_conversions() -> None:
    """Ensure AdminTransactionResponse computed fields convert accurately."""
    now = datetime.now(timezone.utc)
    admin_txn = AdminTransactionResponse(
        id="adm-001",
        reference="TXNADM123",
        user_id="user-001",
        type="TRANSFER",
        amount_minor=250000,
        fee_minor=0,
        total_debit_minor=250000,
        currency="INR",
        status="COMPLETED",
        channel="IMPS",
        created_at=now,
    )
    dumped = admin_txn.model_dump()

    assert admin_txn.amount == 2500.0
    assert admin_txn.amount_rupees == 2500.0
    assert admin_txn.amount_formatted == "₹2,500.00"
    assert dumped["amount_rupees"] == 2500.0


def test_balance_response_rupee_conversions() -> None:
    """Ensure BalanceResponse computed fields convert balance accurately."""
    bal = BalanceResponse(
        bank_name="Test Bank",
        available_minor=5000000,
        currency="INR",
        as_of="19 Nov 2026, 12:00 PM UTC",
    )
    dumped = bal.model_dump()

    assert bal.available_rupees == 50000.0
    assert bal.available_formatted == "₹50,000.00"
    assert dumped["available_rupees"] == 50000.0
    assert dumped["available_formatted"] == "₹50,000.00"
