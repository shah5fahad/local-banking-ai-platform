"""API v1 router registering all endpoints."""
from fastapi import APIRouter

from app.api.v1 import (
    accounts,
    admin,
    approvals,
    audit_logs,
    auth,
    beneficiaries,
    credit_cards,
    dashboard,
    loans,
    transactions,
    transfers,
    users,
)

router = APIRouter(prefix="/api/v1")

for r in [
    auth.router,
    users.router,
    dashboard.router,
    accounts.router,
    beneficiaries.router,
    approvals.router,
    transfers.router,
    transactions.router,
    loans.router,
    credit_cards.router,
    admin.router,
    audit_logs.router,
]:
    router.include_router(r)
