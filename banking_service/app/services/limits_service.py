"""Limits service enforcing transfer thresholds and daily caps."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import BankingSettings
from app.core.errors import BankingError
from app.repositories.transaction_repository import TransactionRepository


class _CheckLimitsDispatcher:
    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            def class_call(
                user_id: str,
                amount_minor: int,
                repo: Any,
                settings: BankingSettings,
                fee_minor: int = 0,
            ) -> None:
                LimitsService._validate_limits(user_id, amount_minor, repo, settings, fee_minor)
            return class_call

        def instance_call(
            user_id: str,
            amount_minor: int,
            fee_minor: int = 0,
            **kwargs: Any,
        ) -> None:
            LimitsService._validate_limits(user_id, amount_minor, obj.repo, obj.settings, fee_minor)
        return instance_call


class _GetLimitsDispatcher:
    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            def class_call(
                user_id: str,
                repo: Any,
                settings: BankingSettings,
            ) -> dict[str, int | str]:
                return LimitsService._retrieve_limits(user_id, repo, settings)
            return class_call

        def instance_call(user_id: str, *args: Any, **kwargs: Any) -> dict[str, int | str]:
            return LimitsService._retrieve_limits(user_id, obj.repo, obj.settings)
        return instance_call


class LimitsService:
    """Enforces per-transaction and cumulative daily transfer limits."""

    def __init__(
        self,
        settings: BankingSettings,
        session_or_repo: Session | TransactionRepository,
    ) -> None:
        self.settings = settings
        if isinstance(session_or_repo, TransactionRepository):
            self.repo = session_or_repo
        else:
            self.repo = TransactionRepository(session_or_repo)

    check_limits = _CheckLimitsDispatcher()
    get_limits = _GetLimitsDispatcher()

    @staticmethod
    def _validate_limits(
        user_id: str,
        amount_minor: int,
        repo: Any,
        settings: BankingSettings,
        fee_minor: int = 0,
    ) -> None:
        total_amount = amount_minor + (fee_minor or 0)
        if total_amount > settings.transfer_per_txn_limit_minor:
            raise BankingError(
                error_code="LIMIT_EXCEEDED",
                message=(
                    f"Amount exceeds per-transaction limit of "
                    f"{settings.transfer_per_txn_limit_minor} minor units."
                ),
                http_status=422,
            )

        daily_used = repo.daily_used_minor(user_id)
        if daily_used + total_amount > settings.transfer_daily_limit_minor:
            remaining = max(0, settings.transfer_daily_limit_minor - daily_used)
            raise BankingError(
                error_code="LIMIT_EXCEEDED",
                message=(
                    f"Transfer exceeds daily limit of {settings.transfer_daily_limit_minor} minor units. "
                    f"Remaining today: {remaining} minor units."
                ),
                http_status=422,
            )

    @staticmethod
    def _retrieve_limits(
        user_id: str,
        repo: Any,
        settings: BankingSettings,
    ) -> dict[str, int | str]:
        daily_used = repo.daily_used_minor(user_id)
        daily_remaining = max(0, settings.transfer_daily_limit_minor - daily_used)
        return {
            "per_transaction_limit_minor": settings.transfer_per_txn_limit_minor,
            "daily_limit_minor": settings.transfer_daily_limit_minor,
            "daily_used_minor": daily_used,
            "daily_remaining_minor": daily_remaining,
            "currency": "INR",
        }


