"""Users API router for profile retrieval and management."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas.dashboard import CustomerDashboardResponse
from app.schemas.user import ResetPinRequest, ResetPinResponse, UserResponse
from app.services.dashboard_service import DashboardService
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
def get_current_user_profile(user: CurrentUser) -> UserResponse:
    """Return profile details for the currently authenticated user."""
    return user  # type: ignore[return-value]


@router.get(
    "/dashboard",
    response_model=CustomerDashboardResponse,
    summary="Get customer dashboard summary",
)
def get_user_dashboard(
    user: CurrentUser,
    db: DbSession,
) -> CustomerDashboardResponse:
    """Return aggregated dashboard data for authenticated user."""
    return DashboardService.get_dashboard(user, db)


@router.post(
    "/pin",
    response_model=ResetPinResponse,
    summary="Reset or regenerate transaction PIN with password verification",
)
def reset_transaction_pin(
    payload: ResetPinRequest,
    user: CurrentUser,
    db: DbSession,
) -> ResetPinResponse:
    """Reset or regenerate transaction PIN by verifying account password."""
    UserService.set_transaction_pin(
        user_id=user.id,
        password=payload.current_password,
        pin=payload.new_pin,
        db=db,
    )
    return ResetPinResponse(
        message="Transaction PIN updated successfully",
        transaction_pin_set=True,
    )


@router.post(
    "/me/pin",
    response_model=ResetPinResponse,
    summary="Reset or regenerate transaction PIN with password verification (alias)",
    include_in_schema=False,
)
def reset_transaction_pin_me_alias(
    payload: ResetPinRequest,
    user: CurrentUser,
    db: DbSession,
) -> ResetPinResponse:
    """Alias for /pin endpoint under /me/pin."""
    return reset_transaction_pin(payload=payload, user=user, db=db)
