"""Unit tests for Auth API endpoints (/api/v1/auth/*)."""
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
def test_client():
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


def test_register_login_refresh_logout_flow(test_client: TestClient) -> None:
    # 1. Register
    reg_resp = test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "phone": "+919876543210",
            "full_name": "Test User",
            "password": "StrongPassword123!",
        },
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert reg_data["email"] == "user@example.com"
    assert "id" in reg_data
    assert reg_data.get("account_id") is not None
    assert reg_data.get("account_number_masked") is not None
    assert reg_data.get("account") is not None
    assert reg_data["account"]["status"] == "ACTIVE"
    assert reg_data["account"]["verification_status"] == "VERIFIED"
    assert reg_data["account"]["holder_name"] == "Test User"
    assert reg_data.get("card_id") is not None
    assert reg_data.get("card_last4") is not None
    assert reg_data.get("card") is not None
    assert reg_data["card"]["status"] == "ACTIVE"
    assert reg_data["card"]["network"] == "VISA"
    assert reg_data["card"]["card_number_masked"].startswith("XXXX-XXXX-XXXX-")
    assert reg_data.get("loan_offers") is not None
    assert len(reg_data["loan_offers"]) >= 3
    loan_types = {o["loan_type"] for o in reg_data["loan_offers"]}
    assert "HOME" in loan_types
    assert "AUTO" in loan_types
    assert "PERSONAL" in loan_types

    # 2. Duplicate registration fails
    dup_resp = test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "phone": "+919876543211",
            "full_name": "Test User 2",
            "password": "StrongPassword123!",
        },
    )
    assert dup_resp.status_code == 409

    # 3. Weak password validation
    weak_resp = test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "weak@example.com",
            "phone": "+919876543299",
            "full_name": "Weak User",
            "password": "short",
        },
    )
    assert weak_resp.status_code == 422

    # 4. Login
    login_resp = test_client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "StrongPassword123!",
        },
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert "access_token" in login_data
    assert "refresh_token" in login_data
    access_token = login_data["access_token"]
    refresh_token = login_data["refresh_token"]

    # 5. Get current profile (/api/v1/users/me)
    auth_headers = {"Authorization": f"Bearer {access_token}"}
    me_resp = test_client.get("/api/v1/users/me", headers=auth_headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "user@example.com"
    assert "CUSTOMER" in me_data["roles"]

    # 5b. Verify auto-created account is accessible (/api/v1/accounts)
    acc_resp = test_client.get("/api/v1/accounts", headers=auth_headers)
    assert acc_resp.status_code == 200
    accounts = acc_resp.json()
    assert len(accounts) == 1
    assert accounts[0]["id"] == reg_data["account_id"]
    assert accounts[0]["status"] == "ACTIVE"
    assert accounts[0]["verification_status"] == "VERIFIED"

    # 5c. Verify auto-created card is accessible (/api/v1/credit-cards)
    cards_resp = test_client.get("/api/v1/credit-cards", headers=auth_headers)
    assert cards_resp.status_code == 200
    cards = cards_resp.json()
    assert len(cards) == 1
    assert cards[0]["id"] == reg_data["card_id"]
    assert cards[0]["status"] == "ACTIVE"
    assert cards[0]["network"] == "VISA"

    # 5d. Verify decrypted sensitive card details (/api/v1/credit-cards/{id}/details)
    detail_resp = test_client.get(f"/api/v1/credit-cards/{reg_data['card_id']}/details", headers=auth_headers)
    assert detail_resp.status_code == 200
    card_details = detail_resp.json()
    assert len(card_details["card_number"]) == 16
    assert len(card_details["cvv"]) == 3
    assert "/" in card_details["expiry_date"]

    # 5e. Verify loan offers accessible (/api/v1/loans/offers)
    offers_resp = test_client.get("/api/v1/loans/offers", headers=auth_headers)
    assert offers_resp.status_code == 200
    offers = offers_resp.json()
    assert len(offers) >= 3
    returned_types = {o["loan_type"] for o in offers}
    assert "HOME" in returned_types
    assert "AUTO" in returned_types
    assert "PERSONAL" in returned_types

    # 6. List active sessions
    sess_resp = test_client.get("/api/v1/auth/sessions", headers=auth_headers)
    assert sess_resp.status_code == 200
    sessions = sess_resp.json()
    assert len(sessions) == 1
    assert sessions[0]["is_current"] is True

    # 7. Refresh token rotation
    ref_resp = test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert ref_resp.status_code == 200
    ref_data = ref_resp.json()
    new_access_token = ref_data["access_token"]
    new_refresh_token = ref_data["refresh_token"]
    assert new_access_token != access_token

    # 8. Reusing old refresh token must be rejected (reuse detection)
    stale_resp = test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert stale_resp.status_code == 401

    # 9. Logout with new token
    new_headers = {"Authorization": f"Bearer {new_access_token}"}
    logout_resp = test_client.post("/api/v1/auth/logout", headers=new_headers)
    assert logout_resp.status_code == 200
    assert logout_resp.json()["message"] == "Logged out successfully"


def test_login_and_register_with_local_domain(test_client: TestClient) -> None:
    """Ensure local/internal domain emails like admin@bank.local are accepted."""
    reg_resp = test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "customer@bank.local",
            "phone": "+919876543210",
            "full_name": "Local User",
            "password": "StrongPassword123!",
        },
    )
    assert reg_resp.status_code == 201

    login_resp = test_client.post(
        "/api/v1/auth/login",
        json={
            "email": "customer@bank.local",
            "password": "StrongPassword123!",
        },
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()
