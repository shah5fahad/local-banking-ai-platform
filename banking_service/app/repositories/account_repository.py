"""Repository for BankAccount aggregates."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import BankAccount

if TYPE_CHECKING:
    from app.core.config import BankingSettings


class AccountRepository:
    """Repository handling database operations for BankAccount entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        user_id: str,
        holder_name: str,
        account_number_encrypted: str,
        last4: str,
        account_number_hash: str,
        ifsc: str,
        bank_name: str,
        branch_name: str | None,
        account_type: str,
        balance_minor: int = 0,
        currency: str = "INR",
        verification_status: str = "PENDING",
        status: str = "ACTIVE",
        settings: BankingSettings | None = None,
    ) -> BankAccount:
        """Create and persist a new BankAccount."""
        account = BankAccount(
            user_id=user_id,
            holder_name=holder_name,
            account_number_encrypted=account_number_encrypted,
            account_number_last4=last4,
            account_number_hash=account_number_hash,
            ifsc=ifsc,
            bank_name=bank_name,
            branch_name=branch_name or "Main Branch",
            account_type=account_type,
            balance_minor=balance_minor,
            currency=currency,
            verification_status=verification_status,
            status=status,
        )
        self.session.add(account)
        self.session.flush()
        self.session.refresh(account)
        return account

    def get_by_id(self, id: str, user_id: str) -> BankAccount | None:
        """Retrieve account by ID strictly scoped to user_id (ownership enforced)."""
        stmt = select(BankAccount).where(
            BankAccount.id == id,
            BankAccount.user_id == user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_for_user(
        self, user_id: str, status: str | None = None
    ) -> list[BankAccount]:
        """List all accounts belonging to user_id, optionally filtered by status."""
        stmt = select(BankAccount).where(BankAccount.user_id == user_id)
        if status:
            stmt = stmt.where(BankAccount.status == status.upper())
        stmt = stmt.order_by(BankAccount.created_at.desc())
        return list(self.session.execute(stmt).scalars().all())

    def get_by_hash(
        self, user_id: str, account_number_hash: str, ifsc: str
    ) -> BankAccount | None:
        """Find existing account by HMAC hash and IFSC for a specific user."""
        stmt = select(BankAccount).where(
            BankAccount.user_id == user_id,
            BankAccount.account_number_hash == account_number_hash,
            BankAccount.ifsc == ifsc,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def update(self, account: BankAccount) -> BankAccount:
        """Update an existing account."""
        self.session.add(account)
        self.session.flush()
        self.session.refresh(account)
        return account

    def deactivate(self, id: str, user_id: str) -> None:
        """Set account status to INACTIVE scoped by user_id."""
        account = self.get_by_id(id, user_id)
        if account:
            account.status = "INACTIVE"
            self.session.add(account)
            self.session.flush()
