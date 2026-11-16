"""Unit tests for Customer Dashboard API endpoints (/api/v1/dashboard, /api/v1/users/dashboard)."""
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


def test_customer_dashboard_returns_accounts_cards_and_loans(test_client: TestClient) -> None:
    # 1. Register a new user (which auto-creates account, card, and 3 loan offers)
    reg_resp = test_client.post(
        "/api/v1/auth/register",
        json={
            "email": "dashuser@example.com",
            "phone": "+919876543299",
            "full_name": "Dashboard Customer",
            "password": "StrongPassword123!",
        },
    )
    assert reg_resp.status_code == 201

    # 2. Login to obtain access token
    login_resp = test_client.post(
        "/api/v1/auth/login",
        json={
            "email": "dashuser@example.com",
            "password": "StrongPassword123!",
        },
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Test GET /api/v1/dashboard
    dash_resp = test_client.get("/api/v1/dashboard", headers=headers)
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()

    # Verify user profile in dashboard
    assert dash_data["user"]["email"] == "dashuser@example.com"
    assert dash_data["user"]["full_name"] == "Dashboard Customer"

    # Verify accounts
    assert len(dash_data["accounts"]) == 1
    assert dash_data["accounts"][0]["holder_name"] == "Dashboard Customer"
    assert dash_data["accounts"][0]["status"] == "ACTIVE"
    assert dash_data["accounts"][0]["verification_status"] == "VERIFIED"
    assert dash_data["total_balance_minor"] == 10_000_000

    # Verify credit cards
    assert len(dash_data["cards"]) == 1
    assert dash_data["cards"][0]["status"] == "ACTIVE"
    assert dash_data["cards"][0]["network"] == "VISA"
    assert dash_data["cards"][0]["card_number_masked"].startswith("XXXX-XXXX-XXXX-")
    assert dash_data["total_credit_limit_minor"] == 20_000_000
    assert dash_data["total_available_credit_minor"] == 20_000_000

    # Verify loan offers (Home, Car/Auto, Personal)
    assert len(dash_data["loan_offers"]) >= 3
    offer_types = {o["loan_type"] for o in dash_data["loan_offers"]}
    assert "HOME" in offer_types
    assert "AUTO" in offer_types
    assert "PERSONAL" in offer_types

    # 4. Test GET /api/v1/users/dashboard alias
    user_dash_resp = test_client.get("/api/v1/users/dashboard", headers=headers)
    assert user_dash_resp.status_code == 200
    assert user_dash_resp.json()["user"]["email"] == "dashuser@example.com"
    assert len(user_dash_resp.json()["accounts"]) == 1
    assert len(user_dash_resp.json()["cards"]) == 1
    assert len(user_dash_resp.json()["loan_offers"]) >= 3
