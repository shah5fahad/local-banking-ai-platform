"""Unit tests for Account and Beneficiary services (T2.5, T2.6)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import BankingSettings
from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_pin
from app.db.base import Base
from app.models.user import User
from app.schemas.account import CreateAccountRequest, UpdateAccountRequest
from app.schemas.beneficiary import CreateBeneficiaryRequest, UpdateBeneficiaryRequest
from app.services.account_service import AccountService
from app.services.beneficiary_service import BeneficiaryService


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
        secret_key="test-secret-key-for-unit-tests-only",
        jwt_secret="test-secret-key-for-unit-tests-only",
    )


@pytest.fixture
def test_user(db_session):
    user = User(
        id="user-test-1",
        email="testuser@example.com",
        phone="+919876543210",
        full_name="Test User",
        password_hash="test-password-hash",
        transaction_pin_hash=hash_pin("1234"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


class TestAccountService:
    def test_add_and_get_account(self, db_session, test_settings, test_user) -> None:
        req = CreateAccountRequest(
            holder_name="Test User",
            account_number="123456789012",
            ifsc="HDFC0001234",
            bank_name="HDFC Bank",
            branch_name="Main Branch",
            account_type="SAVINGS",
        )
        account = AccountService.add_account(test_user.id, req, db_session, test_settings)
        assert account.id is not None
        assert account.user_id == test_user.id
        assert account.account_number_last4 == "9012"
        assert account.account_number_masked == "XXXXXX9012"
        assert account.verification_status == "PENDING"
        assert account.status == "ACTIVE"

        # Retrieve
        fetched = AccountService.get_account(test_user.id, account.id, db_session)
        assert fetched.id == account.id
        assert fetched.holder_name == "Test User"

    def test_duplicate_account_conflict(self, db_session, test_settings, test_user) -> None:
        req = CreateAccountRequest(
            holder_name="Test User",
            account_number="123456789012",
            ifsc="HDFC0001234",
            bank_name="HDFC Bank",
        )
        AccountService.add_account(test_user.id, req, db_session, test_settings)
        with pytest.raises(ConflictError):
            AccountService.add_account(test_user.id, req, db_session, test_settings)

    def test_cross_user_isolation(self, db_session, test_settings, test_user) -> None:
        req = CreateAccountRequest(
            holder_name="Test User",
            account_number="123456789012",
            ifsc="HDFC0001234",
            bank_name="HDFC Bank",
        )
        account = AccountService.add_account(test_user.id, req, db_session, test_settings)
        with pytest.raises(NotFoundError):
            AccountService.get_account("other-user-999", account.id, db_session)

    def test_get_balance_specific_and_missing_account_id(self, db_session, test_settings, test_user) -> None:
        req1 = CreateAccountRequest(
            holder_name="Test User",
            account_number="123456789012",
            ifsc="HDFC0001234",
            bank_name="HDFC Bank",
            account_type="SAVINGS",
        )
        acc1 = AccountService.add_account(test_user.id, req1, db_session, test_settings)
        acc1.balance_minor = 50000
        db_session.commit()

        req2 = CreateAccountRequest(
            holder_name="Test User",
            account_number="987654321098",
            ifsc="ICIC0005678",
            bank_name="ICICI Bank",
            account_type="CURRENT",
        )
        acc2 = AccountService.add_account(test_user.id, req2, db_session, test_settings)
        acc2.balance_minor = 75000
        db_session.commit()

        # 1. Specific account balance
        bal1 = AccountService.get_balance(test_user.id, acc1.id, db_session)
        assert bal1["available_minor"] == 50000
        assert bal1["account_id"] == acc1.id
        assert bal1["bank_name"] == "HDFC Bank"

        # 2. Missing account ID (None) -> automatically gets the top active account (acc2, latest created active)
        bal_auto = AccountService.get_balance(test_user.id, None, db_session)
        assert bal_auto["account_id"] == acc2.id
        assert bal_auto["available_minor"] == 75000
        assert bal_auto["bank_name"] == "ICICI Bank"

        # 3. String alias 'default' -> automatically gets top active account
        bal_default = AccountService.get_balance(test_user.id, "default", db_session)
        assert bal_default["account_id"] == acc2.id
        assert bal_default["bank_name"] == "ICICI Bank"

    def test_get_balance_no_accounts_raises(self, db_session, test_user) -> None:
        with pytest.raises(NotFoundError):
            AccountService.get_balance(test_user.id, None, db_session)


class TestBeneficiaryService:
    def test_challenge_and_add_beneficiary(self, db_session, test_settings, test_user) -> None:
        # 1. Create approval challenge
        challenge = BeneficiaryService.create_challenge(
            user_id=test_user.id,
            action="BENEFICIARY_CREATE",
            payload_hash="dummy-sha256-hash",
            db=db_session,
            settings=test_settings,
        )
        assert challenge.status == "PENDING"

        # 2. Verify challenge with correct PIN
        token = BeneficiaryService.verify_challenge(
            challenge_id=challenge.id,
            pin="1234",
            user_id=test_user.id,
            db=db_session,
            settings=test_settings,
        )
        assert token is not None

        # 3. Create beneficiary using approval token
        req = CreateBeneficiaryRequest(
            name="Rahul Sharma",
            nickname="Rahul",
            account_number="987654321098",
            ifsc="ICIC0000456",
            bank_name="ICICI Bank",
        )
        bene = BeneficiaryService.create_beneficiary(
            user_id=test_user.id,
            data=req,
            approval_token=token,
            db=db_session,
            settings=test_settings,
        )
        assert bene.id is not None
        assert bene.name == "Rahul Sharma"
        assert bene.last4 == "1098"
        assert bene.account_number_masked == "XXXXXX1098"
        assert bene.status == "ACTIVE"

        # 4. Token cannot be reused (consumed)
        with pytest.raises(Exception):
            BeneficiaryService.create_beneficiary(
                user_id=test_user.id,
                data=req,
                approval_token=token,
                db=db_session,
                settings=test_settings,
            )
