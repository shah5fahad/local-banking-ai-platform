"""Unit tests for fee strategy and limit checking (T2.7, T2.8)."""
import pytest
from unittest.mock import MagicMock

from app.core.config import BankingSettings
from app.core.errors import BankingError
from app.services.fee_service import FeeStrategy
from app.services.limits_service import LimitsService


class TestFeeStrategy:
    def test_fee_calculation(self) -> None:
        assert FeeStrategy.calculate_fee("IMPS", 500_000) == 500
        assert FeeStrategy.calculate_fee("NEFT", 500_000) == 0
        assert FeeStrategy.calculate_fee("RTGS", 500_000) == 2500


class TestLimitsService:
    def test_per_txn_limit_exceeded(self) -> None:
        settings = BankingSettings(transfer_per_txn_limit_minor=1_000_000)
        repo = MagicMock()
        with pytest.raises(BankingError) as exc_info:
            LimitsService.check_limits("u1", 2_000_000, repo, settings)
        assert exc_info.value.error_code == "LIMIT_EXCEEDED"

    def test_daily_limit_exceeded(self) -> None:
        settings = BankingSettings(
            transfer_per_txn_limit_minor=5_000_000,
            transfer_daily_limit_minor=10_000_000,
        )
        repo = MagicMock()
        repo.daily_used_minor.return_value = 8_000_000
        with pytest.raises(BankingError) as exc_info:
            LimitsService.check_limits("u1", 3_000_000, repo, settings)
        assert exc_info.value.error_code == "LIMIT_EXCEEDED"
