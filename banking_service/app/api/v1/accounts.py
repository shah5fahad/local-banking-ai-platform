"""Accounts API router for bank account management, verification, and balance checks."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, status

from app.core.deps import AppSettings, CurrentUser, DbSession
from app.schemas.account import (
    AccountResponse,
    BalanceResponse,
    CreateAccountRequest,
    UpdateAccountRequest,
    VerifyAccountResponse,
)
from app.services.account_service import AccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountResponse], summary="List user accounts")
def list_accounts(
    user: CurrentUser,
    db: DbSession,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (e.g. ACTIVE, INACTIVE)"),
) -> list[AccountResponse]:
    """List linked bank accounts for authenticated user."""
    accounts = AccountService.list_accounts(user.id, status=status_filter, db=db)
    return [AccountResponse.model_validate(a) for a in accounts]


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add / link a new bank account",
)
def add_account(
    user: CurrentUser,
    data: CreateAccountRequest,
    db: DbSession,
    settings: AppSettings,
) -> AccountResponse:
    """Add and securely encrypt a new bank account."""
    account = AccountService.add_account(user.id, data, db=db, settings=settings)
    return AccountResponse.model_validate(account)


@router.get("/{id}", response_model=AccountResponse, summary="Get account details")
def get_account(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> AccountResponse:
    """Retrieve details for a specific bank account belonging to authenticated user."""
    account = AccountService.get_account(user.id, id, db=db)
    return AccountResponse.model_validate(account)


@router.patch("/{id}", response_model=AccountResponse, summary="Update non-key account fields")
def update_account(
    id: str,
    data: UpdateAccountRequest,
    user: CurrentUser,
    db: DbSession,
) -> AccountResponse:
    """Update holder name, bank name, or branch."""
    account = AccountService.update_account(user.id, id, data, db=db)
    return AccountResponse.model_validate(account)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate account")
def deactivate_account(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> None:
    """Deactivate a bank account (blocked if pending transactions exist)."""
    AccountService.deactivate_account(user.id, id, db=db)


@router.post("/{id}/verify", response_model=VerifyAccountResponse, summary="Verify account")
def verify_account(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> VerifyAccountResponse:
    """Simulate penny-drop verification for linked account."""
    account = AccountService.verify_account(user.id, id, db=db)
    return VerifyAccountResponse(
        verification_status=account.verification_status,
        message=f"Account verification completed: {account.verification_status}",
    )


@router.get("/{id}/balance", response_model=BalanceResponse, summary="Get account balance")
def get_account_balance(
    id: str,
    user: CurrentUser,
    db: DbSession,
) -> BalanceResponse:
    """Fetch real-time available balance for account."""
    bal = AccountService.get_balance(user.id, id, db=db)
    return BalanceResponse(
        available_minor=bal["available_minor"],
        currency=bal["currency"],
        as_of=bal["as_of"],
    )
