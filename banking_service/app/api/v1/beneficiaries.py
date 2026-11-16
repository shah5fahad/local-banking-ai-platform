"""Beneficiaries API router."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, status

from app.core.deps import AppSettings, CurrentUser, DbSession
from app.schemas.beneficiary import (
    BeneficiaryResponse,
    CreateBeneficiaryRequest,
    UpdateBeneficiaryRequest,
    VerifyBeneficiaryResponse,
)
from app.services.beneficiary_service import BeneficiaryService

router = APIRouter(prefix="/beneficiaries", tags=["beneficiaries"])


@router.get("", response_model=list[BeneficiaryResponse], summary="List beneficiaries")
def list_beneficiaries(
    user: CurrentUser,
    db: DbSession,
    q: str | None = None,
) -> list[BeneficiaryResponse]:
    """List active beneficiaries for authenticated user with optional name search."""
    beneficiaries = BeneficiaryService.list_beneficiaries(user.id, q=q, db=db)
    return [BeneficiaryResponse.model_validate(b) for b in beneficiaries]


@router.post(
    "",
    response_model=BeneficiaryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create beneficiary",
)
def create_beneficiary(
    user: CurrentUser,
    data: CreateBeneficiaryRequest,
    db: DbSession,
    settings: AppSettings,
    x_approval_token: Annotated[str, Header(alias="X-Approval-Token")],
) -> BeneficiaryResponse:
    """Create a new beneficiary. Requires X-Approval-Token header from verified challenge."""
    bene = BeneficiaryService.create_beneficiary(
        user_id=user.id,
        data=data,
        approval_token=x_approval_token,
        db=db,
        settings=settings,
    )
    return BeneficiaryResponse.model_validate(bene)


@router.get("/{bene_id}", response_model=BeneficiaryResponse, summary="Get beneficiary details")
def get_beneficiary(
    bene_id: str,
    user: CurrentUser,
    db: DbSession,
) -> BeneficiaryResponse:
    """Retrieve details for a specific beneficiary belonging to user."""
    bene = BeneficiaryService.get_beneficiary(user.id, bene_id, db=db)
    return BeneficiaryResponse.model_validate(bene)


@router.patch("/{bene_id}", response_model=BeneficiaryResponse, summary="Update beneficiary")
def update_beneficiary(
    bene_id: str,
    user: CurrentUser,
    data: UpdateBeneficiaryRequest,
    db: DbSession,
    settings: AppSettings,
    x_approval_token: Annotated[str, Header(alias="X-Approval-Token")],
) -> BeneficiaryResponse:
    """Update non-key beneficiary details.
    
    Resets verification status and consumes approval token.
    """
    bene = BeneficiaryService.update_beneficiary(
        user_id=user.id,
        bene_id=bene_id,
        data=data,
        approval_token=x_approval_token,
        db=db,
        settings=settings,
    )
    return BeneficiaryResponse.model_validate(bene)


@router.delete(
    "/{bene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate beneficiary",
)
def deactivate_beneficiary(
    bene_id: str,
    user: CurrentUser,
    db: DbSession,
) -> None:
    """Deactivate a beneficiary for current user."""
    BeneficiaryService.deactivate_beneficiary(user.id, bene_id, db=db)


@router.post(
    "/{bene_id}/verify",
    response_model=VerifyBeneficiaryResponse,
    summary="Verify beneficiary",
)
def verify_beneficiary(
    bene_id: str,
    user: CurrentUser,
    db: DbSession,
) -> VerifyBeneficiaryResponse:
    """Mock penny-drop verification for a beneficiary."""
    bene = BeneficiaryService.verify_beneficiary(user.id, bene_id, db=db)
    return VerifyBeneficiaryResponse(
        verification_status=bene.verification_status,
        message="Beneficiary account verified successfully via penny-drop mock",
    )
