"""Tests for LimitsService and compute_fee strategy (T2.7)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import BankingSettings
from app.core.errors import BankingError
from app.db.base import Base
from app.services.fee_strategy import compute_fee
from app.services.limits_service import LimitsService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_settings():
    return BankingSettings(
        transfer_per_txn_limit_minor=20_000_000,
        transfer_daily_limit_minor=50_000_000,
    )


class TestFeeStrategy:
    def test_imps_fee_below_ten_thousand(self) -> None:
        # Amount 5000 INR = 500,000 paise -> 500 paise (Rs 5)
        fee = compute_fee(500_000, "IMPS")
        assert fee == 500

    def test_imps_fee_at_or_above_ten_thousand(self) -> None:
        # Amount 10,000 INR = 1,000,000 paise -> 1000 paise (Rs 10)
        fee = compute_fee(1_000_000, "IMPS")
        assert fee == 1000

        # Amount 25,000 INR -> 1000 paise
        fee2 = compute_fee(2_500_000, "IMPS")
        assert fee2 == 1000

    def test_neft_fee(self) -> None:
        # NEFT flat Rs 2.50 = 250 paise
        assert compute_fee(100_000, "NEFT") == 250
        assert compute_fee(5_000_000, "NEFT") == 250

    def test_rtgs_fee(self) -> None:
        # RTGS flat Rs 20 = 2000 paise
        assert compute_fee(20_000_000, "RTGS") == 2000

    def test_default_fee(self) -> None:
        # Other / default -> 500 paise
        assert compute_fee(50_000, "OTHER") == 500
        assert compute_fee(50_000, "") == 500


class TestLimitsService:
    def test_limits_within_bounds(self, db_session, test_settings) -> None:
        service = LimitsService(test_settings, db_session)
        # Should not raise
        service.check_limits(user_id="user-123", amount_minor=100_000, fee_minor=500)

    def test_per_txn_limit_exceeded(self, db_session, test_settings) -> None:
        service = LimitsService(test_settings, db_session)
        # Limit is 20,000,000 paise. 20,000,001 should raise
        with pytest.raises(BankingError) as exc_info:
            service.check_limits(
                user_id="user-123",
                amount_minor=20_000_000,
                fee_minor=100,
            )
        assert exc_info.value.error_code == "LIMIT_EXCEEDED"
        assert exc_info.value.http_status == 422

    def test_get_limits_summary(self, db_session, test_settings) -> None:
        service = LimitsService(test_settings, db_session)
        limits = service.get_limits("user-123")
        assert limits["per_transaction_limit_minor"] == 20_000_000
        assert limits["daily_limit_minor"] == 50_000_000
        assert limits["daily_used_minor"] == 0
        assert limits["daily_remaining_minor"] == 50_000_000
        assert limits["currency"] == "INR"
