"""Integration test for auto-creating bank account upon user signup (T7.1)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app


@pytest.fixture
def client():
    """Create in-memory SQLite database and test client."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_end_to_end_signup_auto_creates_verified_bank_account(client: TestClient) -> None:
    """AC: new user registration automatically creates an initial active bank account."""
    # 1. Register new customer
    payload = {
        "email": "priya.sharma@example.com",
        "phone": "+919811122233",
        "full_name": "Priya Sharma",
        "password": "SecurePassword2024!",
    }
    reg_res = client.post("/api/v1/auth/register", json=payload)
    assert reg_res.status_code == 201
    reg_data = reg_res.json()

    assert reg_data["email"] == "priya.sharma@example.com"
    assert reg_data["full_name"] == "Priya Sharma"
    assert reg_data["account_id"] is not None
    assert reg_data["account_number_masked"].startswith("XXXXXX")
    assert reg_data["account"] is not None
    assert reg_data["account"]["holder_name"] == "Priya Sharma"
    assert reg_data["account"]["status"] == "ACTIVE"
    assert reg_data["account"]["verification_status"] == "VERIFIED"
    assert reg_data["account"]["account_type"] == "SAVINGS"
    assert reg_data["account"]["currency"] == "INR"

    account_id = reg_data["account_id"]

    # 2. Login to get access token
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Fetch linked accounts via GET /api/v1/accounts
    list_res = client.get("/api/v1/accounts", headers=headers)
    assert list_res.status_code == 200
    accounts = list_res.json()
    assert len(accounts) == 1
    assert accounts[0]["id"] == account_id
    assert accounts[0]["holder_name"] == "Priya Sharma"
    assert accounts[0]["status"] == "ACTIVE"
    assert accounts[0]["verification_status"] == "VERIFIED"

    # 4. Fetch specific account details via GET /api/v1/accounts/{id}
    detail_res = client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == account_id
    assert detail["holder_name"] == "Priya Sharma"
    assert detail["status"] == "ACTIVE"
    assert detail["verification_status"] == "VERIFIED"
    assert detail["balance_minor"] == 10_000_000

    # 5. Check real-time balance via GET /api/v1/accounts/{id}/balance
    bal_res = client.get(f"/api/v1/accounts/{account_id}/balance", headers=headers)
    assert bal_res.status_code == 200
    bal_data = bal_res.json()
    assert bal_data["available_minor"] == 10_000_000
    assert bal_data["currency"] == "INR"


def test_multiple_signups_create_distinct_accounts(client: TestClient) -> None:
    """Ensure two different users get distinct bank accounts with proper isolation."""
    user1 = {
        "email": "user1@example.com",
        "phone": "+919811100001",
        "full_name": "User One",
        "password": "Password123!@",
    }
    user2 = {
        "email": "user2@example.com",
        "phone": "+919811100002",
        "full_name": "User Two",
        "password": "Password123!@",
    }

    r1 = client.post("/api/v1/auth/register", json=user1)
    r2 = client.post("/api/v1/auth/register", json=user2)

    assert r1.status_code == 201
    assert r2.status_code == 201

    d1 = r1.json()
    d2 = r2.json()

    assert d1["id"] != d2["id"]
    assert d1["account_id"] != d2["account_id"]
    assert d1["account"]["account_number_masked"] != d2["account"]["account_number_masked"]

    # Verify user 1 cannot access user 2's account
    l1 = client.post("/api/v1/auth/login", json={"email": user1["email"], "password": user1["password"]})
    token1 = l1.json()["access_token"]
    h1 = {"Authorization": f"Bearer {token1}"}

    cross_res = client.get(f"/api/v1/accounts/{d2['account_id']}", headers=h1)
    assert cross_res.status_code == 404


def test_end_to_end_signup_auto_creates_active_card(client: TestClient) -> None:
    """AC: new user registration automatically provisions an active card securely linked to user."""
    payload = {
        "email": "carduser@example.com",
        "phone": "+919811199887",
        "full_name": "Cardholder User",
        "password": "SecurePassword2024!",
    }
    reg_res = client.post("/api/v1/auth/register", json=payload)
    assert reg_res.status_code == 201
    reg_data = reg_res.json()

    # 1. Verify card returned in registration response
    assert reg_data["card_id"] is not None
    assert reg_data["card_last4"] is not None
    assert reg_data["card"] is not None
    assert reg_data["card"]["status"] == "ACTIVE"
    assert reg_data["card"]["network"] == "VISA"
    assert reg_data["card"]["card_number_masked"].startswith("XXXX-XXXX-XXXX-")
    assert reg_data["card"]["credit_limit_minor"] == 20_000_000

    card_id = reg_data["card_id"]

    # 2. Login
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. List cards via GET /api/v1/credit-cards
    list_res = client.get("/api/v1/credit-cards", headers=headers)
    assert list_res.status_code == 200
    cards = list_res.json()
    assert len(cards) == 1
    assert cards[0]["id"] == card_id
    assert cards[0]["status"] == "ACTIVE"
    assert cards[0]["network"] == "VISA"

    # 4. Fetch card details via GET /api/v1/credit-cards/{id}
    detail_res = client.get(f"/api/v1/credit-cards/{card_id}", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == card_id
    assert detail["status"] == "ACTIVE"
    assert detail["card_number_masked"].endswith(reg_data["card_last4"])

    # 5. Fetch sensitive decrypted details via GET /api/v1/credit-cards/{id}/details
    sens_res = client.get(f"/api/v1/credit-cards/{card_id}/details", headers=headers)
    assert sens_res.status_code == 200
    sens = sens_res.json()
    assert sens["card_id"] == card_id
    assert len(sens["card_number"]) == 16
    assert len(sens["cvv"]) == 3
    assert sens["card_number"].endswith(reg_data["card_last4"])
    assert "/" in sens["expiry_date"]


def test_end_to_end_signup_auto_creates_three_loan_offers(client: TestClient) -> None:
    """AC: newly registered user has at least 3 distinct loan offers accessible via loans API."""
    payload = {
        "email": "loanuser@example.com",
        "phone": "+919811199333",
        "full_name": "Loan Applicant User",
        "password": "SecurePassword2024!",
    }
    reg_res = client.post("/api/v1/auth/register", json=payload)
    assert reg_res.status_code == 201
    reg_data = reg_res.json()

    # 1. Verify 3 loan offers returned in registration response
    assert reg_data["loan_offers"] is not None
    assert len(reg_data["loan_offers"]) >= 3
    offer_types = {o["loan_type"] for o in reg_data["loan_offers"]}
    assert "HOME" in offer_types
    assert "AUTO" in offer_types
    assert "PERSONAL" in offer_types

    # 2. Login to get access token
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Query GET /api/v1/loans/offers
    offers_res = client.get("/api/v1/loans/offers", headers=headers)
    assert offers_res.status_code == 200
    offers = offers_res.json()
    assert len(offers) >= 3

    types_found = set()
    for o in offers:
        assert o["status"] == "ACTIVE"
        assert o["rate_bps"] > 0
        assert o["max_amount_minor"] > 0
        assert o["min_tenure_months"] > 0
        assert o["max_tenure_months"] >= o["min_tenure_months"]
        types_found.add(o["loan_type"])

    assert "HOME" in types_found
    assert "AUTO" in types_found
    assert "PERSONAL" in types_found

    # 4. Fetch specific offer details GET /api/v1/loans/offers/{id}
    first_offer = offers[0]
    single_res = client.get(f"/api/v1/loans/offers/{first_offer['id']}", headers=headers)
    assert single_res.status_code == 200
    single = single_res.json()
    assert single["id"] == first_offer["id"]
    assert single["loan_type"] == first_offer["loan_type"]
