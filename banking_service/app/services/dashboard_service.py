"""Customer dashboard service aggregating accounts, cards, and loan offers."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.account import AccountResponse
from app.schemas.credit_card import CreditCardResponse
from app.schemas.dashboard import CustomerDashboardResponse
from app.schemas.loan import LoanOfferResponse
from app.schemas.user import UserResponse
from app.services.account_service import AccountService
from app.services.card_service import CardService
from app.services.loan_service import LoanService


class DashboardService:
    """Service generating customer dashboard summary."""

    @staticmethod
    def get_dashboard(user: User, db: Session) -> CustomerDashboardResponse:
        """Fetch and aggregate bank accounts, cards, and loan offers for authenticated user."""
        raw_accounts = AccountService.list_accounts(user.id, status=None, db=db)
        accounts = [AccountResponse.model_validate(a) for a in raw_accounts]

        raw_cards = CardService.list_cards(user.id, db=db)
        cards = [CreditCardResponse.model_validate(c) for c in raw_cards]

        raw_offers = LoanService.get_offers(user.id, db=db)
        loan_offers = [LoanOfferResponse.model_validate(o) for o in raw_offers]

        total_balance = sum(
            a.balance_minor for a in accounts if a.status == "ACTIVE"
        )
        total_credit_limit = sum(
            c.credit_limit_minor for c in cards if c.status == "ACTIVE"
        )
        total_available_credit = sum(
            max(0, c.credit_limit_minor - c.outstanding_minor)
            for c in cards
            if c.status == "ACTIVE"
        )

        return CustomerDashboardResponse(
            user=UserResponse.model_validate(user),
            accounts=accounts,
            cards=cards,
            loan_offers=loan_offers,
            total_balance_minor=total_balance,
            total_credit_limit_minor=total_credit_limit,
            total_available_credit_minor=total_available_credit,
            as_of=datetime.now(timezone.utc),
        )
