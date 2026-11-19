"""Unit tests for Approvals API endpoints (/api/v1/approvals/*)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password, hash_pin
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models.user import Role, User


@pytest.fixture
def db_session_and_client():
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
    session = TestingSessionLocal()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield session, c
    session.close()
    app.dependency_overrides.clear()


def test_create_and_verify_approval_challenge(db_session_and_client) -> None:
    session, client = db_session_and_client

    # 1. Register a new user
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "approval@example.com",
            "phone": "+919876543211",
            "full_name": "Approval User",
            "password": "StrongPassword123!",
            "pin": "1234",
        },
    )
    assert reg_resp.status_code == 201

    # 2. Login to obtain access token
    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "approval@example.com",
            "password": "StrongPassword123!",
        },
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Set transaction PIN on the user
    user = session.query(User).filter(User.email == "approval@example.com").first()
    assert user is not None
    user.transaction_pin_hash = hash_pin("1234")
    session.commit()

    # 2. POST /api/v1/approvals/challenges
    # Previously this failed with TypeError: can't subtract offset-naive and offset-aware datetimes
    resp = client.post(
        "/api/v1/approvals/challenges",
        headers=headers,
        json={
            "action": "BENEFICIARY_CREATE",
            "payload_hash": "a" * 64,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "challenge_id" in data
    assert data["action"] == "BENEFICIARY_CREATE"
    assert data["expires_in_seconds"] > 0
    assert data["expires_in_seconds"] <= 300

    challenge_id = data["challenge_id"]

    # 3. POST /api/v1/approvals/challenges/{challenge_id}/verify
    verify_resp = client.post(
        f"/api/v1/approvals/challenges/{challenge_id}/verify",
        headers=headers,
        json={
            "pin": "1234",
        },
    )
    assert verify_resp.status_code == 200, verify_resp.text
    verify_data = verify_resp.json()
    assert "approval_token" in verify_data
    assert verify_data["expires_in"] > 0
