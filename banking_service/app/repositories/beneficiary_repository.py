"""Repository for Beneficiary entities."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.beneficiary import Beneficiary


class BeneficiaryRepository:
    """Repository handling database operations for Beneficiary entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        user_id: str,
        name: str,
        nickname: str | None,
        account_number_encrypted: str,
        last4: str,
        account_number_hash: str,
        ifsc: str,
        bank_name: str,
    ) -> Beneficiary:
        """Create and persist a new Beneficiary."""
        beneficiary = Beneficiary(
            user_id=user_id,
            name=name,
            nickname=nickname,
            account_number_encrypted=account_number_encrypted,
            last4=last4,
            account_hash=account_number_hash,
            ifsc=ifsc,
            bank_name=bank_name,
            verification_status="PENDING",
            approval_status="APPROVED",
            status="ACTIVE",
        )
        self.session.add(beneficiary)
        self.session.flush()
        self.session.refresh(beneficiary)
        return beneficiary

    def get_by_id(self, id: str, user_id: str) -> Beneficiary | None:
        """Retrieve beneficiary strictly scoped to user_id (ownership enforced)."""
        stmt = select(Beneficiary).where(
            Beneficiary.id == id,
            Beneficiary.user_id == user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_for_user(
        self, user_id: str, q: str | None = None
    ) -> list[Beneficiary]:
        """List active beneficiaries for user, optionally matching name or nickname."""
        stmt = select(Beneficiary).where(
            Beneficiary.user_id == user_id,
            Beneficiary.status == "ACTIVE",
        )
        if q and q.strip():
            search = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Beneficiary.name).like(search),
                    func.lower(Beneficiary.nickname).like(search),
                )
            )
        stmt = stmt.order_by(Beneficiary.created_at.desc())
        return list(self.session.execute(stmt).scalars().all())

    def get_by_hash(
        self, user_id: str, account_number_hash: str, ifsc: str
    ) -> Beneficiary | None:
        """Find existing beneficiary by user_id, account_hash, and ifsc."""
        stmt = select(Beneficiary).where(
            Beneficiary.user_id == user_id,
            Beneficiary.account_hash == account_number_hash,
            Beneficiary.ifsc == ifsc,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def update(self, beneficiary: Beneficiary) -> Beneficiary:
        """Update an existing beneficiary."""
        self.session.add(beneficiary)
        self.session.flush()
        self.session.refresh(beneficiary)
        return beneficiary

    def deactivate(self, id: str, user_id: str) -> None:
        """Deactivate beneficiary by setting status to INACTIVE."""
        bene = self.get_by_id(id, user_id)
        if bene:
            bene.status = "INACTIVE"
            self.session.add(bene)
            self.session.flush()
