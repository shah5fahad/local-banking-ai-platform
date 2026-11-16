"""Transaction repository for database operations on BankTransaction and TransferAuthorization."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.transaction import BankTransaction, TransferAuthorization


class TransactionRepository:
    """Repository handling transactions and transfer authorizations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        user_id: str,
        source_account_id: str,
        beneficiary_id: str,
        amount_minor: int,
        fee_minor: int,
        total_debit_minor: int,
        channel: str,
        remark: Optional[str],
        currency: str,
        reference: str,
        summary_hash: str,
        idempotency_key: Optional[str],
        expires_at: Optional[datetime],
        type: str = "TRANSFER",
        status: str = "PENDING_APPROVAL",
    ) -> BankTransaction:
        """Create and persist a new BankTransaction record."""
        txn = BankTransaction(
            user_id=user_id,
            source_account_id=source_account_id,
            beneficiary_id=beneficiary_id,
            amount_minor=amount_minor,
            fee_minor=fee_minor,
            total_debit_minor=total_debit_minor,
            channel=channel,
            remark=remark,
            currency=currency,
            reference=reference,
            summary_hash=summary_hash,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
            type=type,
            status=status,
        )
        self.session.add(txn)
        self.session.flush()
        return txn

    def get_by_id(self, id: str, user_id: Optional[str] = None) -> BankTransaction | None:
        """Fetch transaction by ID, enforcing user ownership if user_id is provided."""
        stmt = select(BankTransaction).where(BankTransaction.id == id)
        if user_id is not None:
            stmt = stmt.where(BankTransaction.user_id == user_id)
        return self.session.scalar(stmt)

    def get_by_reference(
        self, reference: str, user_id: Optional[str] = None
    ) -> BankTransaction | None:
        """Fetch transaction by unique reference."""
        stmt = select(BankTransaction).where(BankTransaction.reference == reference)
        if user_id is not None:
            stmt = stmt.where(BankTransaction.user_id == user_id)
        return self.session.scalar(stmt)

    def get_by_idempotency_key(
        self, user_id: str, idempotency_key: str
    ) -> BankTransaction | None:
        """Find an existing transaction by user_id and idempotency key."""
        stmt = select(BankTransaction).where(
            BankTransaction.user_id == user_id,
            BankTransaction.idempotency_key == idempotency_key,
        )
        return self.session.scalar(stmt)

    def update_status(
        self,
        txn_id: str,
        status: str,
        failure_reason: Optional[str] = None,
        executed_at: Optional[datetime] = None,
    ) -> None:
        """Update transaction status and execution details."""
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if failure_reason is not None:
            values["failure_reason"] = failure_reason
        if executed_at is not None:
            values["executed_at"] = executed_at

        stmt = update(BankTransaction).where(BankTransaction.id == txn_id).values(**values)
        self.session.execute(stmt)
        self.session.flush()

    def list_for_user(
        self,
        user_id: Optional[str],
        filters: dict[str, Any],
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[BankTransaction], int]:
        """Query transactions with filters, pagination, and ownership."""
        stmt = select(BankTransaction)
        count_stmt = select(func.count(BankTransaction.id))

        if user_id is not None:
            stmt = stmt.where(BankTransaction.user_id == user_id)
            count_stmt = count_stmt.where(BankTransaction.user_id == user_id)

        if "status" in filters and filters["status"]:
            stmt = stmt.where(BankTransaction.status == filters["status"])
            count_stmt = count_stmt.where(BankTransaction.status == filters["status"])

        if "type" in filters and filters["type"]:
            stmt = stmt.where(BankTransaction.type == filters["type"])
            count_stmt = count_stmt.where(BankTransaction.type == filters["type"])

        if "beneficiary_id" in filters and filters["beneficiary_id"]:
            stmt = stmt.where(BankTransaction.beneficiary_id == filters["beneficiary_id"])
            count_stmt = count_stmt.where(BankTransaction.beneficiary_id == filters["beneficiary_id"])

        if "reference" in filters and filters["reference"]:
            stmt = stmt.where(BankTransaction.reference == filters["reference"])
            count_stmt = count_stmt.where(BankTransaction.reference == filters["reference"])

        if "min_amount_minor" in filters and filters["min_amount_minor"] is not None:
            stmt = stmt.where(BankTransaction.amount_minor >= filters["min_amount_minor"])
            count_stmt = count_stmt.where(BankTransaction.amount_minor >= filters["min_amount_minor"])

        if "max_amount_minor" in filters and filters["max_amount_minor"] is not None:
            stmt = stmt.where(BankTransaction.amount_minor <= filters["max_amount_minor"])
            count_stmt = count_stmt.where(BankTransaction.amount_minor <= filters["max_amount_minor"])

        if "from_date" in filters and filters["from_date"]:
            stmt = stmt.where(BankTransaction.created_at >= filters["from_date"])
            count_stmt = count_stmt.where(BankTransaction.created_at >= filters["from_date"])

        if "to_date" in filters and filters["to_date"]:
            stmt = stmt.where(BankTransaction.created_at <= filters["to_date"])
            count_stmt = count_stmt.where(BankTransaction.created_at <= filters["to_date"])

        total = self.session.scalar(count_stmt) or 0
        offset = (max(page, 1) - 1) * page_size
        items = list(
            self.session.scalars(
                stmt.order_by(BankTransaction.created_at.desc()).offset(offset).limit(page_size)
            ).all()
        )
        return items, total

    def create_authorization(
        self,
        transaction_id: str,
        method: str,
        challenge_hash: str,
        summary_hash: str,
        expires_at: datetime,
    ) -> TransferAuthorization:
        """Create and persist a TransferAuthorization challenge."""
        auth = TransferAuthorization(
            transaction_id=transaction_id,
            method=method,
            challenge_hash=challenge_hash,
            summary_hash=summary_hash,
            status="ISSUED",
            attempts=0,
            expires_at=expires_at,
        )
        self.session.add(auth)
        self.session.flush()
        return auth

    def get_authorization(self, txn_id: str) -> TransferAuthorization | None:
        """Get authorization linked to a transaction."""
        stmt = select(TransferAuthorization).where(TransferAuthorization.transaction_id == txn_id)
        return self.session.scalar(stmt)

    def get_authorization_by_id(self, auth_id: str) -> TransferAuthorization | None:
        """Get authorization by its primary ID."""
        stmt = select(TransferAuthorization).where(TransferAuthorization.id == auth_id)
        return self.session.scalar(stmt)

    def update_authorization(
        self,
        auth_id: str,
        status: str,
        attempts: Optional[int] = None,
        consumed_at: Optional[datetime] = None,
    ) -> None:
        """Update authorization status, attempt count, or consumed timestamp."""
        values: dict[str, Any] = {"status": status}
        if attempts is not None:
            values["attempts"] = attempts
        if consumed_at is not None:
            values["consumed_at"] = consumed_at

        stmt = update(TransferAuthorization).where(TransferAuthorization.id == auth_id).values(**values)
        self.session.execute(stmt)
        self.session.flush()

    def daily_used_minor(self, user_id: str) -> int:
        """Sum total completed + processing transfers initiated by user today (UTC)."""
        now = datetime.now(timezone.utc)
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        stmt = select(func.coalesce(func.sum(BankTransaction.amount_minor), 0)).where(
            BankTransaction.user_id == user_id,
            BankTransaction.status.in_(["COMPLETED", "PROCESSING"]),
            BankTransaction.created_at >= start_of_day,
        )
        return int(self.session.scalar(stmt) or 0)

    def check_duplicate_window(
        self,
        user_id: str,
        beneficiary_id: str,
        amount_minor: int,
        window_seconds: int,
    ) -> BankTransaction | None:
        """Check if a transfer with same beneficiary and amount was created within window."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        stmt = select(BankTransaction).where(
            BankTransaction.user_id == user_id,
            BankTransaction.beneficiary_id == beneficiary_id,
            BankTransaction.amount_minor == amount_minor,
            BankTransaction.status.not_in(["CANCELLED", "EXPIRED", "FAILED"]),
            BankTransaction.created_at >= cutoff,
        ).order_by(BankTransaction.created_at.desc())
        return self.session.scalar(stmt)
