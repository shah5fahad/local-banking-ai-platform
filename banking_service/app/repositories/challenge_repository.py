"""Repository for ApprovalChallenge entities."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.approval_challenge import ApprovalChallenge


class ChallengeRepository:
    """Repository handling database operations for ApprovalChallenge entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        user_id: str,
        action: str,
        payload_hash: str,
        pin_hash: str | None,
        expires_at: datetime,
    ) -> ApprovalChallenge:
        """Create and persist an approval challenge."""
        challenge = ApprovalChallenge(
            user_id=user_id,
            action=action,
            payload_hash=payload_hash,
            pin_hash=pin_hash,
            status="PENDING",
            attempts=0,
            expires_at=expires_at,
        )
        self.session.add(challenge)
        self.session.flush()
        self.session.refresh(challenge)
        return challenge

    def get_by_id(self, id: str) -> ApprovalChallenge | None:
        """Retrieve challenge by ID."""
        stmt = select(ApprovalChallenge).where(ApprovalChallenge.id == id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_token_hash(
        self, approval_token_hash: str
    ) -> ApprovalChallenge | None:
        """Retrieve challenge by its hashed approval token."""
        stmt = select(ApprovalChallenge).where(
            ApprovalChallenge.approval_token_hash == approval_token_hash
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def mark_verified(
        self, id: str, approval_token_hash: str
    ) -> ApprovalChallenge | None:
        """Mark challenge as VERIFIED and record single-use approval token hash."""
        challenge = self.get_by_id(id)
        if challenge:
            challenge.status = "VERIFIED"
            challenge.approval_token_hash = approval_token_hash
            self.session.add(challenge)
            self.session.flush()
            self.session.refresh(challenge)
        return challenge

    def consume(self, id: str) -> None:
        """Consume single-use approval challenge."""
        challenge = self.get_by_id(id)
        if challenge:
            challenge.status = "CONSUMED"
            challenge.consumed_at = datetime.now(timezone.utc)
            self.session.add(challenge)
            self.session.flush()

    def expire_old(self, db: Session | None = None) -> int:
        """Transition past-expiry PENDING challenges to EXPIRED."""
        sess = db or self.session
        now = datetime.now(timezone.utc)
        stmt = (
            update(ApprovalChallenge)
            .where(
                ApprovalChallenge.status == "PENDING",
                ApprovalChallenge.expires_at < now,
            )
            .values(status="EXPIRED")
        )
        result = sess.execute(stmt)
        sess.flush()
        return result.rowcount
