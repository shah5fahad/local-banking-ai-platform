"""Loans API router for offers, eligibility checks, applications, and repayment schedules."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, status

from app.core.deps import CurrentUser, DbSession
from app.schemas.loan import (
    EligibilityRequest,
    EligibilityResponse,
    LoanApplicationRequest,
    LoanApplicationResponse,
    LoanOfferResponse,
    RepaymentScheduleResponse,
)
from app.services.loan_service import LoanService

router = APIRouter(prefix="/loans", tags=["loans"])


@router.get("/offers", response_model=list[LoanOfferResponse], summary="List available loan offers")
def list_loan_offers(
    user: CurrentUser,
    db: DbSession,
) -> list[LoanOfferResponse]:
    """Return pre-approved and generic loan offers for the current user."""
    offers = LoanService.get_offers(user.id, db)
    return [LoanOfferResponse.model_validate(o) for o in offers]


@router.get("/offers/{id}", response_model=LoanOfferResponse, summary="Get loan offer detail")
def get_loan_offer(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> LoanOfferResponse:
    """Fetch specific loan offer details."""
    offer = LoanService.get_offer(user.id, id, db)
    return LoanOfferResponse.model_validate(offer)


@router.post("/eligibility", response_model=EligibilityResponse, summary="Check loan eligibility")
def check_loan_eligibility(
    user: CurrentUser,
    data: EligibilityRequest,
    db: DbSession,
) -> EligibilityResponse:
    """Evaluate eligibility for a requested loan amount and tenure."""
    eligible, max_amount_minor, reasons = LoanService.evaluate_eligibility(user.id, data, db)
    return EligibilityResponse(
        eligible=eligible,
        max_amount_minor=max_amount_minor,
        reasons=reasons,
    )


@router.get("/active", response_model=list[LoanApplicationResponse], summary="List active loans")
def list_active_loans(
    user: CurrentUser,
    db: DbSession,
) -> list[LoanApplicationResponse]:
    """Return user's active (APPROVED) loans."""
    loans = LoanService.list_active_loans(user.id, db)
    return [LoanApplicationResponse.model_validate(l) for l in loans]


@router.post(
    "/applications",
    response_model=LoanApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit loan application",
)
def apply_for_loan(
    user: CurrentUser,
    data: LoanApplicationRequest,
    db: DbSession,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> LoanApplicationResponse:
    """Submit a new loan application with idempotency guarantee."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None

    app = LoanService.apply(
        user_id=user.id,
        data=data,
        idempotency_key=idempotency_key,
        db=db,
        request_id=request_id,
        ip=ip,
    )
    db.commit()
    return LoanApplicationResponse.model_validate(app)


@router.get(
    "/applications",
    response_model=list[LoanApplicationResponse],
    summary="List loan applications",
)
def list_loan_applications(
    user: CurrentUser,
    db: DbSession,
) -> list[LoanApplicationResponse]:
    """List all submitted loan applications for current user."""
    apps = LoanService.list_applications(user.id, db)
    return [LoanApplicationResponse.model_validate(a) for a in apps]


@router.get(
    "/applications/{id}",
    response_model=LoanApplicationResponse,
    summary="Get loan application detail",
)
def get_loan_application(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> LoanApplicationResponse:
    """Fetch status and details of a specific application."""
    app = LoanService.get_application(user.id, id, db)
    return LoanApplicationResponse.model_validate(app)


@router.get(
    "/{id}/repayment",
    response_model=RepaymentScheduleResponse,
    summary="Get loan repayment schedule",
)
def get_repayment_schedule(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> RepaymentScheduleResponse:
    """Return monthly EMI amortization schedule for a loan."""
    repayment_data = LoanService.get_repayment(user.id, id, db)
    return RepaymentScheduleResponse(**repayment_data)
