"""Credit Cards API router for cards, balances, statements, and payments."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Header, Query, Request, status

from app.core.deps import AppSettings, CurrentUser, DbSession
from app.schemas.credit_card import (
    AuthorizePaymentRequest,
    CardPaymentRequest,
    CardPaymentResponse,
    CreditCardResponse,
    ExecutePaymentRequest,
    OutstandingResponse,
    SensitiveCardDetailsResponse,
    StatementListResponse,
    StatementResponse,
)
from app.services.card_service import CardService

router = APIRouter(prefix="/credit-cards", tags=["credit-cards"])


@router.get("", response_model=list[CreditCardResponse], summary="List credit cards")
def list_credit_cards(
    user: CurrentUser,
    db: DbSession,
) -> list[CreditCardResponse]:
    """List all credit cards owned by current user."""
    cards = CardService.list_cards(user.id, db)
    return [CreditCardResponse.model_validate(c) for c in cards]


# ---------------------------------------------------------------------------
# Specific payments routes (placed before /{id} to avoid path collision)
# ---------------------------------------------------------------------------


@router.post(
    "/payments/{id}/authorize",
    response_model=CardPaymentResponse,
    summary="Authorize credit card payment",
)
def authorize_card_payment(
    id: str,
    data: AuthorizePaymentRequest,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> CardPaymentResponse:
    """Authorize a card payment with transaction PIN."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None

    payment = CardService.authorize_payment(
        user_id=user.id,
        payment_id=id,
        pin_or_otp=data.pin or data.otp,
        db=db,
        settings=settings,
        request_id=request_id,
        ip=ip,
    )
    db.commit()
    return CardPaymentResponse.model_validate(payment)


@router.post(
    "/payments/{id}/execute",
    response_model=CardPaymentResponse,
    summary="Execute authorized card payment",
)
def execute_card_payment(
    id: str,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
    data: Optional[ExecutePaymentRequest] = None,
) -> CardPaymentResponse:
    """Execute authorized credit card payment."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None
    auth_id = data.authorization_id if data else None

    payment = CardService.execute_payment(
        user_id=user.id,
        payment_id=id,
        authorization_id=auth_id,
        db=db,
        settings=settings,
        request_id=request_id,
        ip=ip,
    )
    db.commit()
    return CardPaymentResponse.model_validate(payment)


@router.get(
    "/payments/{id}/status",
    response_model=CardPaymentResponse,
    summary="Get card payment status",
)
def get_card_payment_status(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> CardPaymentResponse:
    """Get status of a card payment."""
    payment = CardService.get_payment(user.id, id, db)
    return CardPaymentResponse.model_validate(payment)


# ---------------------------------------------------------------------------
# Card-specific routes (/{id}/...)
# ---------------------------------------------------------------------------


@router.get("/{id}", response_model=CreditCardResponse, summary="Get credit card detail")
def get_credit_card(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> CreditCardResponse:
    """Fetch details of a specific card owned by user."""
    card = CardService.get_card(user.id, id, db)
    return CreditCardResponse.model_validate(card)


@router.get(
    "/{id}/details",
    response_model=SensitiveCardDetailsResponse,
    summary="Get sensitive card details (number, expiry, CVV)",
)
def get_sensitive_card_details(
    id: str,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> SensitiveCardDetailsResponse:
    """Fetch decrypted card details (card number, expiration date, CVV) for the cardholder."""
    details = CardService.get_card_sensitive_details(user.id, id, db, settings)
    return SensitiveCardDetailsResponse(**details)


@router.get(
    "/{id}/outstanding",
    response_model=OutstandingResponse,
    summary="Get card outstanding balance",
)
def get_card_outstanding(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> OutstandingResponse:
    """Fetch outstanding balance and available credit."""
    data = CardService.get_outstanding(user.id, id, db)
    return OutstandingResponse(**data)


@router.get(
    "/{id}/statements",
    response_model=StatementListResponse,
    summary="List card statements",
)
def get_card_statements(
    id: str,
    user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> StatementListResponse:
    """List paginated statements for a card."""
    items, total = CardService.get_statements(user.id, id, page, page_size, db)
    return StatementListResponse(
        items=[StatementResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{id}/bills/current",
    response_model=StatementResponse,
    summary="Get current card statement bill",
)
def get_current_card_bill(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> StatementResponse:
    """Fetch the latest billing statement for a card."""
    stmt = CardService.get_current_bill(user.id, id, db)
    return StatementResponse.model_validate(stmt)


@router.post(
    "/{id}/payments",
    response_model=CardPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Prepare card payment",
)
def prepare_card_payment(
    id: str,
    data: CardPaymentRequest,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> CardPaymentResponse:
    """Prepare a credit card payment."""
    request_id = getattr(request.state, "request_id", None)
    ip = request.client.host if request.client else None

    payment = CardService.prepare_payment(
        user_id=user.id,
        card_id=id,
        data=data,
        idempotency_key=idempotency_key,
        db=db,
        settings=settings,
        request_id=request_id,
        ip=ip,
    )
    db.commit()
    return CardPaymentResponse.model_validate(payment)


@router.get(
    "/{id}/payments",
    response_model=list[CardPaymentResponse],
    summary="List payments for card",
)
def list_card_payments(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> list[CardPaymentResponse]:
    """List historical payments made toward this card."""
    payments = CardService.list_payments(user.id, id, db)
    return [CardPaymentResponse.model_validate(p) for p in payments]
