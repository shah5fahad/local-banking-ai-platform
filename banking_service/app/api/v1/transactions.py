"""Transactions API router for transaction history, filtering, pagination, and lookup."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.transaction import TransactionListResponse, TransactionResponse

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionListResponse, summary="List user transactions")
def list_transactions(
    user: CurrentUser,
    db: DbSession,
    from_date: Optional[datetime] = Query(None, description="Start created_at timestamp"),
    to_date: Optional[datetime] = Query(None, description="End created_at timestamp"),
    type: Optional[str] = Query(None, description="Transaction type filter (e.g. TRANSFER, CARD_PAYMENT)"),
    min_amount_minor: Optional[int] = Query(None, ge=0, description="Minimum amount in minor units (paise)"),
    max_amount_minor: Optional[int] = Query(None, ge=0, description="Maximum amount in minor units (paise)"),
    min_amount: Optional[float] = Query(None, ge=0, description="Minimum amount in rupees"),
    max_amount: Optional[float] = Query(None, ge=0, description="Maximum amount in rupees"),
    status: Optional[str] = Query(None, description="Status filter (e.g. COMPLETED, PENDING_APPROVAL)"),
    beneficiary_id: Optional[str] = Query(None, description="Beneficiary UUID filter"),
    reference: Optional[str] = Query(None, description="Transaction reference filter"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
) -> TransactionListResponse:
    """List transactions for current user with filtering, sorting, and pagination."""
    repo = TransactionRepository(db)
    effective_min_minor = min_amount_minor if min_amount_minor is not None else (int(round(min_amount * 100)) if min_amount is not None else None)
    effective_max_minor = max_amount_minor if max_amount_minor is not None else (int(round(max_amount * 100)) if max_amount is not None else None)
    filters = {
        "from_date": from_date,
        "to_date": to_date,
        "type": type,
        "min_amount_minor": effective_min_minor,
        "max_amount_minor": effective_max_minor,
        "status": status,
        "beneficiary_id": beneficiary_id,
        "reference": reference,
    }
    items, total = repo.list_for_user(user.id, filters, page=page, page_size=page_size)
    has_next = (page * page_size) < total

    return TransactionListResponse(
        items=[TransactionResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.get(
    "/by-reference/{ref}",
    response_model=TransactionResponse,
    summary="Get transaction by reference",
)
def get_transaction_by_reference(
    ref: str,
    user: CurrentUser,
    db: DbSession,
) -> TransactionResponse:
    """Fetch transaction by unique reference for current user."""
    repo = TransactionRepository(db)
    txn = repo.get_by_reference(ref, user_id=user.id)
    if not txn:
        raise NotFoundError("Transaction", ref)
    return TransactionResponse.model_validate(txn)


@router.get("/{id}", response_model=TransactionResponse, summary="Get transaction by ID")
def get_transaction_by_id(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> TransactionResponse:
    """Fetch transaction by ID for current user."""
    repo = TransactionRepository(db)
    txn = repo.get_by_id(id, user_id=user.id)
    if not txn:
        raise NotFoundError("Transaction", id)
    return TransactionResponse.model_validate(txn)
