"""Unit tests for AuthService and account lockout."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import BankingSettings
from app.core.errors import BankingError, ConflictError
from app.core.security import verify_pin
from app.db.base import Base
import app.models  # noqa: F401
from app.services.auth_service import AuthService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_register_success(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    user = auth_service.register(
        email="test@example.com",
        phone="+919876543210",
        full_name="Alice Smith",
        password="ValidPassword123!",
        db=db_session,
        settings=settings,
        pin="1234",
    )
    db_session.commit()

    assert user.id is not None
    assert user.email == "test@example.com"
    assert user.failed_login_count == 0
    assert len(user.roles) == 1
    assert user.roles[0].role.name == "CUSTOMER"

    # Verify auto-created primary bank account (T7.1)
    assert len(user.accounts) == 1
    account = user.accounts[0]
    assert account.user_id == user.id
    assert account.holder_name == "Alice Smith"
    assert account.status == "ACTIVE"
    assert account.verification_status == "VERIFIED"
    assert account.account_type == "SAVINGS"
    assert account.currency == "INR"
    assert account.balance_minor == 10_000_000
    assert len(account.account_number_last4) == 4
    assert account.account_number_masked.startswith("XXXXXX")

    # Verify auto-created active credit card (T7.2)
    assert len(user.credit_cards) == 1
    card = user.credit_cards[0]
    assert card.user_id == user.id
    assert card.status == "ACTIVE"
    assert card.network == "VISA"
    assert card.credit_limit_minor == 20_000_000
    assert card.outstanding_minor == 0
    assert len(card.last4) == 4
    assert card.card_number_masked.startswith("XXXX-XXXX-XXXX-")
    assert card.expiry_date is not None
    assert card.cvv_encrypted is not None
    assert card.card_number_encrypted is not None

    # Verify auto-created loan offers (T7.3)
    assert len(user.loan_offers) >= 3
    offer_types = {o.loan_type for o in user.loan_offers}
    assert "HOME" in offer_types
    assert "AUTO" in offer_types
    assert "PERSONAL" in offer_types
    for o in user.loan_offers:
        assert o.user_id == user.id
        assert o.status == "ACTIVE"
        assert o.rate_bps > 0
        assert o.max_amount_minor > 0
        assert o.terms is not None
        assert o.name is not None


def test_register_without_auto_create_loans(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    user = auth_service.register(
        email="noloans@example.com",
        phone="+919876543213",
        full_name="Dave NoLoans",
        password="ValidPassword123!",
        db=db_session,
        settings=settings,
        auto_create_loans=False,
        pin="1234",
    )
    db_session.commit()

    assert user.id is not None
    assert len(user.loan_offers) == 0


def test_register_without_auto_create_card(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    user = auth_service.register(
        email="nocard@example.com",
        phone="+919876543212",
        full_name="Charlie NoCard",
        password="ValidPassword123!",
        db=db_session,
        settings=settings,
        auto_create_card=False,
        pin="1234",
    )
    db_session.commit()

    assert user.id is not None
    assert len(user.credit_cards) == 0


def test_register_without_auto_create_account(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    user = auth_service.register(
        email="noaccount@example.com",
        phone="+919876543211",
        full_name="Bob NoAccount",
        password="ValidPassword123!",
        db=db_session,
        settings=settings,
        auto_create_account=False,
        pin="1234",
    )
    db_session.commit()

    assert user.id is not None
    assert len(user.accounts) == 0


def test_register_weak_password_fails(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    with pytest.raises(BankingError) as exc:
        auth_service.register(
            email="test@example.com",
            phone="+919876543210",
            full_name="Alice Smith",
            password="weak",
            db=db_session,
            settings=settings,
            pin="1234",
        )
    assert exc.value.http_status == 422


def test_register_duplicate_email_conflict(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    auth_service.register(
        email="dup@example.com",
        phone="+919876543210",
        full_name="Alice Smith",
        password="ValidPassword123!",
        db=db_session,
        settings=settings,
        pin="1234",
    )
    db_session.commit()

    with pytest.raises(ConflictError):
        auth_service.register(
            email="dup@example.com",
            phone="+919876543211",
            full_name="Bob Smith",
            password="ValidPassword123!",
            db=db_session,
            settings=settings,
            pin="1234",
        )


def test_login_success_and_failed_lockout(db_session) -> None:
    settings = BankingSettings(
        jwt_secret="a-very-long-test-jwt-secret-key-min-32-chars"
    )
    auth_service = AuthService()

    auth_service.register(
        email="login@example.com",
        phone="+919876543210",
        full_name="Alice Login",
        password="ValidPassword123!",
        db=db_session,
        settings=settings,
        pin="1234",
    )
    db_session.commit()

    # 4 incorrect attempts
    for i in range(1, 5):
        with pytest.raises(BankingError) as exc:
            auth_service.login(
                email="login@example.com",
                password="WrongPassword123!",
                user_agent="pytest",
                ip="127.0.0.1",
                db=db_session,
                settings=settings,
            )
        assert exc.value.http_status == 401

    # 5th attempt locks the account
    with pytest.raises(BankingError) as exc:
        auth_service.login(
            email="login@example.com",
            password="WrongPassword123!",
            user_agent="pytest",
            ip="127.0.0.1",
            db=db_session,
            settings=settings,
        )
    assert exc.value.http_status == 423
    assert exc.value.error_code == "ACCOUNT_LOCKED"


def test_register_with_valid_4digit_pin(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    user = auth_service.register(
        email="pin4@example.com",
        phone="+919876543201",
        full_name="Pin User 4",
        password="ValidPassword123!",
        db=db_session,
        settings=settings,
        pin="4321",
    )
    db_session.commit()

    assert user.transaction_pin_hash is not None
    assert verify_pin("4321", user.transaction_pin_hash) is True
    assert verify_pin("0000", user.transaction_pin_hash) is False


def test_register_with_valid_6digit_pin(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    user = auth_service.register(
        email="pin6@example.com",
        phone="+919876543202",
        full_name="Pin User 6",
        password="ValidPassword123!",
        db=db_session,
        settings=settings,
        pin="654321",
    )
    db_session.commit()

    assert user.transaction_pin_hash is not None
    assert verify_pin("654321", user.transaction_pin_hash) is True


def test_register_without_pin_raises_error(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    with pytest.raises(BankingError) as exc:
        auth_service.register(
            email="nopin@example.com",
            phone="+919876543203",
            full_name="No Pin User",
            password="ValidPassword123!",
            db=db_session,
            settings=settings,
            pin=None,
        )
    assert exc.value.http_status == 422
    assert exc.value.error_code == "INVALID_PIN_FORMAT"


def test_register_with_invalid_pin_format_raises(db_session) -> None:
    settings = BankingSettings()
    auth_service = AuthService()

    for invalid_pin in ["123", "1234567", "abcd", "12a4", "  "]:
        with pytest.raises(BankingError) as exc:
            auth_service.register(
                email=f"badpin_{invalid_pin.strip()}@example.com",
                phone="+919876543204",
                full_name="Bad Pin User",
                password="ValidPassword123!",
                db=db_session,
                settings=settings,
                pin=invalid_pin,
            )
        assert exc.value.http_status == 422
        assert exc.value.error_code == "INVALID_PIN_FORMAT"

