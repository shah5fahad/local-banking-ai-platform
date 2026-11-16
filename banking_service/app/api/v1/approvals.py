"""Approvals API router for challenge-response authentication."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status

from app.core.deps import AppSettings, CurrentUser, DbSession, RequireCustomerOnly
from app.schemas.beneficiary import (
    ChallengeRequest,
    ChallengeResponse,
    VerifyChallengeRequest,
    VerifyChallengeResponse,
)
from app.services.beneficiary_service import BeneficiaryService

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post(
    "/challenges",
    response_model=ChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create approval challenge",
)
def create_challenge(
    user: CurrentUser,
    body: ChallengeRequest,
    db: DbSession,
    settings: AppSettings,
) -> ChallengeResponse:
    """Issue a new approval challenge for a sensitive operation (e.g. BENEFICIARY_CREATE)."""
    challenge = BeneficiaryService.create_challenge(
        user_id=user.id,
        action=body.action,
        payload_hash=body.payload_hash,
        db=db,
        settings=settings,
    )
    now = datetime.now(UTC)
    remaining_secs = max(0, int((challenge.expires_at - now).total_seconds()))
    return ChallengeResponse(
        challenge_id=challenge.id,
        action=challenge.action,
        expires_in_seconds=remaining_secs,
    )


@router.post(
    "/challenges/{challenge_id}/verify",
    response_model=VerifyChallengeResponse,
    summary="Verify challenge with PIN",
)
def verify_challenge(
    challenge_id: str,
    user: RequireCustomerOnly,
    body: VerifyChallengeRequest,
    db: DbSession,
    settings: AppSettings,
) -> VerifyChallengeResponse:
    """Verify challenge directly with customer PIN and issue single-use approval token."""
    token = BeneficiaryService.verify_challenge(
        challenge_id=challenge_id,
        pin=body.pin,
        user_id=user.id,
        db=db,
        settings=settings,
    )
    expiry = getattr(settings, "transfer_approval_expiry_seconds", 300)
    return VerifyChallengeResponse(
        approval_token=token,
        expires_in=expiry,
    )
