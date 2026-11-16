"""Users API router for profile retrieval and management."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas.dashboard import CustomerDashboardResponse
from app.schemas.user import UserResponse
from app.services.dashboard_service import DashboardService

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
