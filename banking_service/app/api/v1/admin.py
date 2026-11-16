"""Admin API router for platform statistics, user management, loan reviews, and system configuration."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import AppSettings, DbSession, RequireAdmin
from app.core.errors import ConflictError, NotFoundError
from app.core.security import mask_account_number
from app.models.account import BankAccount
from app.models.loan import LoanApplication
from app.models.transaction import BankTransaction
from app.models.user import Role, User, UserRole
from app.schemas.admin import (
    AdminLoanResponse,
    AdminStatsResponse,
    AdminTransactionResponse,
    AdminUserResponse,
    ConfigResponse,
    UpdateConfigRequest,
    UpdateUserRolesRequest,
    UpdateUserStatusRequest,
)
from app.services.audit_service import AuditService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStatsResponse, summary="Get system-wide statistics")
def get_system_stats(
    admin: RequireAdmin,
    db: DbSession,
    request: Request,
) -> AdminStatsResponse:
    """Aggregate high-level system metrics across users, accounts, transactions, and loans."""
    total_users = db.scalar(select(func.count(User.id))) or 0
    active_users = db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
    total_accounts = db.scalar(select(func.count(BankAccount.id))) or 0
    total_transactions = db.scalar(select(func.count(BankTransaction.id))) or 0
    total_loans = db.scalar(select(func.count(LoanApplication.id))) or 0
    total_loan_amount = (
        db.scalar(select(func.coalesce(func.sum(LoanApplication.amount_minor), 0))) or 0
    )

    request_id = getattr(request.state, "request_id", None)
    AuditService.log(
        db=db,
        actor_user_id=admin.id,
        actor_type="ADMIN",
        action="ADMIN_STATS_VIEW",
        resource_type="system",
        outcome="SUCCESS",
        request_id=request_id,
    )
    db.commit()

    return AdminStatsResponse(
        total_users=total_users,
        active_users=active_users,
        total_accounts=total_accounts,
        total_transactions=total_transactions,
        total_loans_submitted=total_loans,
        total_loan_amount_minor=int(total_loan_amount),
    )


@router.get("/users", response_model=list[AdminUserResponse], summary="List all users")
def list_users(
    admin: RequireAdmin,
    db: DbSession,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[AdminUserResponse]:
    """List registered users with pagination and assigned roles."""
    offset = (page - 1) * page_size
    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    users = list(db.scalars(stmt).all())

    request_id = getattr(request.state, "request_id", None)
    AuditService.log(
        db=db,
        actor_user_id=admin.id,
        actor_type="ADMIN",
        action="ADMIN_USERS_LIST",
        resource_type="user",
        outcome="SUCCESS",
        request_id=request_id,
    )
    db.commit()

    return [
        AdminUserResponse(
            id=u.id,
            email=u.email,
            phone=u.phone,
            full_name=u.full_name,
            is_active=u.is_active,
            failed_login_count=u.failed_login_count,
            locked_until=u.locked_until,
            roles=[r.name for r in u.roles],
            created_at=u.created_at,
        )
        for u in users
    ]


@router.patch("/users/{id}/status", response_model=AdminUserResponse, summary="Update user active status")
def update_user_status(
    id: str,
    data: UpdateUserStatusRequest,
    admin: RequireAdmin,
    db: DbSession,
    request: Request,
) -> AdminUserResponse:
    """Activate or deactivate a user account."""
    user = db.scalar(select(User).options(selectinload(User.roles)).where(User.id == id))
    if not user:
        raise NotFoundError("User", id)

    user.is_active = data.is_active
    db.flush()

    request_id = getattr(request.state, "request_id", None)
    AuditService.log(
        db=db,
        actor_user_id=admin.id,
        actor_type="ADMIN",
        action="ADMIN_USER_STATUS_UPDATE",
        resource_type="user",
        resource_id=user.id,
        outcome="SUCCESS",
        request_id=request_id,
        details={"is_active": user.is_active},
    )
    db.commit()

    return AdminUserResponse(
        id=user.id,
        email=user.email,
        phone=user.phone,
        full_name=user.full_name,
        is_active=user.is_active,
        failed_login_count=user.failed_login_count,
        locked_until=user.locked_until,
        roles=[r.name for r in user.roles],
        created_at=user.created_at,
    )


@router.put("/users/{id}/roles", response_model=AdminUserResponse, summary="Update user roles")
def update_user_roles(
    id: str,
    data: UpdateUserRolesRequest,
    admin: RequireAdmin,
    db: DbSession,
    request: Request,
) -> AdminUserResponse:
    """Assign or replace roles for a user."""
    user = db.scalar(select(User).options(selectinload(User.roles)).where(User.id == id))
    if not user:
        raise NotFoundError("User", id)

    # Fetch corresponding Role objects
    roles = list(db.scalars(select(Role).where(Role.name.in_(data.roles))).all())
    if len(roles) != len(set(data.roles)):
        raise ConflictError(f"One or more roles invalid: {data.roles}")

    user.roles = roles
    db.flush()

    request_id = getattr(request.state, "request_id", None)
    AuditService.log(
        db=db,
        actor_user_id=admin.id,
        actor_type="ADMIN",
        action="ADMIN_USER_ROLES_UPDATE",
        resource_type="user",
        resource_id=user.id,
        outcome="SUCCESS",
        request_id=request_id,
        details={"assigned_roles": data.roles},
    )
    db.commit()

    return AdminUserResponse(
        id=user.id,
        email=user.email,
        phone=user.phone,
        full_name=user.full_name,
        is_active=user.is_active,
        failed_login_count=user.failed_login_count,
        locked_until=user.locked_until,
        roles=[r.name for r in user.roles],
        created_at=user.created_at,
    )


@router.get(
    "/transactions",
    response_model=list[AdminTransactionResponse],
    summary="List all transactions (Admin)",
)
def list_admin_transactions(
    admin: RequireAdmin,
    db: DbSession,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[AdminTransactionResponse]:
    """View transactions across all users with masked source accounts."""
    offset = (page - 1) * page_size
    stmt = (
        select(BankTransaction)
        .order_by(BankTransaction.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    txns = list(db.scalars(stmt).all())

    # Pre-load accounts for masking
    account_ids = {t.source_account_id for t in txns if t.source_account_id}
    accounts = (
        {a.id: a for a in db.scalars(select(BankAccount).where(BankAccount.id.in_(account_ids))).all()}
        if account_ids
        else {}
    )

    request_id = getattr(request.state, "request_id", None)
    AuditService.log(
        db=db,
        actor_user_id=admin.id,
        actor_type="ADMIN",
        action="ADMIN_TRANSACTIONS_VIEW",
        resource_type="bank_transaction",
        outcome="SUCCESS",
        request_id=request_id,
    )
    db.commit()

    results: list[AdminTransactionResponse] = []
    for t in txns:
        acc = accounts.get(t.source_account_id) if t.source_account_id else None
        masked_acc = mask_account_number(acc.account_number_last4) if acc else None
        results.append(
            AdminTransactionResponse(
                id=t.id,
                reference=t.reference,
                user_id=t.user_id,
                type=t.type,
                amount_minor=t.amount_minor,
                fee_minor=t.fee_minor,
                total_debit_minor=t.total_debit_minor,
                currency=t.currency,
                status=t.status,
                channel=t.channel,
                source_account_masked=masked_acc,
                beneficiary_id=t.beneficiary_id,
                failure_reason=t.failure_reason,
                created_at=t.created_at,
                executed_at=t.executed_at,
            )
        )
    return results


@router.get(
    "/loan-applications",
    response_model=list[AdminLoanResponse],
    summary="List all loan applications (Admin)",
)
def list_admin_loan_applications(
    admin: RequireAdmin,
    db: DbSession,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[AdminLoanResponse]:
    """View all submitted loan applications across the platform."""
    offset = (page - 1) * page_size
    stmt = (
        select(LoanApplication)
        .order_by(LoanApplication.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    loans = list(db.scalars(stmt).all())

    request_id = getattr(request.state, "request_id", None)
    AuditService.log(
        db=db,
        actor_user_id=admin.id,
        actor_type="ADMIN",
        action="ADMIN_LOANS_VIEW",
        resource_type="loan_application",
        outcome="SUCCESS",
        request_id=request_id,
    )
    db.commit()

    return [AdminLoanResponse.model_validate(l) for l in loans]


@router.get("/config", response_model=ConfigResponse, summary="Get banking configuration")
def get_banking_config(
    admin: RequireAdmin,
    settings: AppSettings,
) -> ConfigResponse:
    """Retrieve active runtime limits and approval settings."""
    return ConfigResponse(
        transfer_per_txn_limit_minor=settings.transfer_per_txn_limit_minor,
        transfer_daily_limit_minor=settings.transfer_daily_limit_minor,
        transfer_approval_expiry_seconds=settings.transfer_approval_expiry_seconds,
        duplicate_window_seconds=settings.duplicate_window_seconds,
        txn_auth_method=settings.txn_auth_method,
        txn_auth_max_attempts=settings.txn_auth_max_attempts,
    )


@router.patch("/config", response_model=ConfigResponse, summary="Update banking configuration")
def update_banking_config(
    data: UpdateConfigRequest,
    admin: RequireAdmin,
    db: DbSession,
    settings: AppSettings,
    request: Request,
) -> ConfigResponse:
    """Update runtime limits, approval expiry, and duplicate detection parameters."""
    updates: dict[str, Any] = {}
    if data.transfer_per_txn_limit_minor is not None:
        settings.transfer_per_txn_limit_minor = data.transfer_per_txn_limit_minor
        updates["transfer_per_txn_limit_minor"] = data.transfer_per_txn_limit_minor

    if data.transfer_daily_limit_minor is not None:
        settings.transfer_daily_limit_minor = data.transfer_daily_limit_minor
        updates["transfer_daily_limit_minor"] = data.transfer_daily_limit_minor

    if data.transfer_approval_expiry_seconds is not None:
        settings.transfer_approval_expiry_seconds = data.transfer_approval_expiry_seconds
        updates["transfer_approval_expiry_seconds"] = data.transfer_approval_expiry_seconds

    if data.duplicate_window_seconds is not None:
        settings.duplicate_window_seconds = data.duplicate_window_seconds
        updates["duplicate_window_seconds"] = data.duplicate_window_seconds

    if data.txn_auth_method is not None:
        settings.txn_auth_method = data.txn_auth_method
        updates["txn_auth_method"] = data.txn_auth_method

    if data.txn_auth_max_attempts is not None:
        settings.txn_auth_max_attempts = data.txn_auth_max_attempts
        updates["txn_auth_max_attempts"] = data.txn_auth_max_attempts

    request_id = getattr(request.state, "request_id", None)
    AuditService.log(
        db=db,
        actor_user_id=admin.id,
        actor_type="ADMIN",
        action="ADMIN_CONFIG_UPDATE",
        resource_type="system_config",
        outcome="SUCCESS",
        request_id=request_id,
        details=updates,
    )
    db.commit()

    return ConfigResponse(
        transfer_per_txn_limit_minor=settings.transfer_per_txn_limit_minor,
        transfer_daily_limit_minor=settings.transfer_daily_limit_minor,
        transfer_approval_expiry_seconds=settings.transfer_approval_expiry_seconds,
        duplicate_window_seconds=settings.duplicate_window_seconds,
        txn_auth_method=settings.txn_auth_method,
        txn_auth_max_attempts=settings.txn_auth_max_attempts,
    )
