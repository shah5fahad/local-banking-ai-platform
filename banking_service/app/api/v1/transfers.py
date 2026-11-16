"""Transfers API router supporting prepare, challenge, authorize, execute, and cancel."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, status
from sqlalchemy import select

from app.core.config import BankingSettings
from app.core.deps import AppSettings, CurrentUser, DbSession, RequireCustomerOnly
from app.core.errors import NotFoundError
from app.core.security import mask_account_number
from app.models.account import BankAccount
from app.models.beneficiary import Beneficiary
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.transfer import (
    AuthorizeChallengeResponse,
    AuthorizeTransferRequest,
    AuthorizeTransferResponse,
    ExecuteTransferRequest,
    LimitsResponse,
    PrepareTransferRequest,
    PrepareTransferResponse,
    TransferDetailResponse,
    TransferStatusResponse,
)
from app.services.limits_service import LimitsService
from app.services.transfer_service import TransferService

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.get("/limits", response_model=LimitsResponse, summary="Get user transfer limits")
def get_transfer_limits(
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> LimitsResponse:
    """Return per-transaction and daily remaining limits for current user."""
    repo = TransactionRepository(db)
    limits_data = LimitsService.get_limits(user.id, repo, settings)
    return LimitsResponse(**limits_data)  # type: ignore[arg-type]


@router.post(
    "",
    response_model=PrepareTransferResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Prepare a transfer",
)
def prepare_transfer(
    user: CurrentUser,
    data: PrepareTransferRequest,
    db: DbSession,
    settings: AppSettings,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> PrepareTransferResponse:
    """Initiate a transfer request, validating accounts, limits, and creating a pending transaction."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None

    txn = TransferService.prepare(
        user_id=user.id,
        data=data,
        idempotency_key=idempotency_key,
        db=db,
        settings=settings,
        request_id=request_id,
        ip=ip,
    )

    # Load beneficiary details for response
    bene = db.scalar(select(Beneficiary).where(Beneficiary.id == txn.beneficiary_id))
    beneficiary_dict = {
        "id": bene.id if bene else txn.beneficiary_id,
        "name": bene.name if bene else "Unknown",
        "account_masked": mask_account_number(bene.last4 if bene else "XXXX"),
        "bank_name": bene.bank_name if bene else "",
        "ifsc": bene.ifsc if bene else "",
    }

    source_acc = db.scalar(select(BankAccount).where(BankAccount.id == txn.source_account_id))
    avail_balance_after = (source_acc.balance_minor - txn.total_debit_minor) if source_acc else 0

    db.commit()
    return PrepareTransferResponse(
        id=txn.id,
        reference=txn.reference,
        status=txn.status,
        beneficiary=beneficiary_dict,
        amount_minor=txn.amount_minor,
        fee_minor=txn.fee_minor,
        total_debit_minor=txn.total_debit_minor,
        currency=txn.currency,
        available_balance_after_minor=avail_balance_after,
        summary_hash=txn.summary_hash or "",
        expires_at=txn.expires_at,  # type: ignore[arg-type]
    )


@router.get("/{id}", response_model=TransferDetailResponse, summary="Get transfer detail")
def get_transfer_detail(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> TransferDetailResponse:
    """Fetch full detail of a transfer owned by the current user."""
    repo = TransactionRepository(db)
    txn = repo.get_by_id(id, user_id=user.id)
    if not txn:
        raise NotFoundError("Transfer", id)
    return TransferDetailResponse.model_validate(txn)


@router.get("/{id}/status", response_model=TransferStatusResponse, summary="Get transfer status")
def get_transfer_status(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> TransferStatusResponse:
    """Fetch transfer status only."""
    repo = TransactionRepository(db)
    txn = repo.get_by_id(id, user_id=user.id)
    if not txn:
        raise NotFoundError("Transfer", id)
    return TransferStatusResponse(
        id=txn.id,
        reference=txn.reference,
        status=txn.status,
        updated_at=txn.updated_at,
    )


@router.post(
    "/{id}/authorize/challenge",
    response_model=AuthorizeChallengeResponse,
    summary="Create authorization challenge",
)
def create_transfer_challenge(
    id: str,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> AuthorizeChallengeResponse:
    """Issue a PIN or OTP authorization challenge."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None

    auth = TransferService.create_auth_challenge(
        user_id=user.id,
        txn_id=id,
        db=db,
        settings=settings,
        request_id=request_id,
        ip=ip,
    )
    db.commit()
    return AuthorizeChallengeResponse(
        challenge_id=auth.id,
        method=auth.method,
        expires_in_seconds=300,
    )


@router.post(
    "/{id}/authorize",
    response_model=AuthorizeTransferResponse,
    summary="Authorize transfer (Customer only)",
)
def authorize_transfer(
    id: str,
    user: RequireCustomerOnly,
    data: AuthorizeTransferRequest,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> AuthorizeTransferResponse:
    """Verify challenge and authorize transfer. Submitted directly by customer."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None

    auth = TransferService.authorize(
        user_id=user.id,
        txn_id=id,
        challenge_id=data.challenge_id,
        pin_or_otp=data.pin or data.otp,
        db=db,
        settings=settings,
        request_id=request_id,
        ip=ip,
    )
    db.commit()
    return AuthorizeTransferResponse(
        authorization_id=auth.id,
        status=auth.status,
    )


@router.post(
    "/{id}/execute",
    response_model=TransferDetailResponse,
    summary="Execute authorized transfer",
)
def execute_transfer(
    id: str,
    user: CurrentUser,
    data: ExecuteTransferRequest,
    db: DbSession,
    settings: AppSettings,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> TransferDetailResponse:
    """Execute transfer: atomic balance deduction and completion."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None

    txn = TransferService.execute(
        user_id=user.id,
        txn_id=id,
        authorization_id=data.authorization_id,
        summary_hash=data.summary_hash,
        idempotency_key=idempotency_key,
        db=db,
        settings=settings,
        request_id=request_id,
        ip=ip,
    )
    db.commit()
    return TransferDetailResponse.model_validate(txn)


@router.post(
    "/{id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel transfer",
)
def cancel_transfer(
    id: str,
    user: CurrentUser,
    db: DbSession,
    request: Request,
) -> None:
    """Cancel a pending transfer."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None

    TransferService.cancel(
        user_id=user.id,
        txn_id=id,
        db=db,
        request_id=request_id,
        ip=ip,
    )
    db.commit()
