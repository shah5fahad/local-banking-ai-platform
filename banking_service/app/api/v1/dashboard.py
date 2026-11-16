"""Customer Dashboard API router."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas.dashboard import CustomerDashboardResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=CustomerDashboardResponse, summary="Get customer dashboard")
def get_customer_dashboard(
    user: CurrentUser,
    db: DbSession,
) -> CustomerDashboardResponse:
    """Fetch customer dashboard summary with accounts, cards, loan offers, and aggregate balances."""
    return DashboardService.get_dashboard(user, db)
