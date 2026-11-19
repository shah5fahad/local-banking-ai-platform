"""Unit tests for Users API endpoints (/api/v1/users/*)."""
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
from app.models.audit_log import AuditLog
from app.models.user import User


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
        yield c, TestingSessionLocal
    app.dependency_overrides.clear()


def _register_and_login(client: TestClient, email: str = "alice@example.com", initial_pin: str | None = "1234") -> tuple[str, str]:
    payload = {
        "email": email,
        "phone": "+919876543210",
        "full_name": "Alice Wonderland",
        "password": "StrongPassword123!",
    }
    if initial_pin:
        payload["pin"] = initial_pin

    reg_resp = client.post("/api/v1/auth/register", json=payload)
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["id"]

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassword123!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return token, user_id


def test_reset_pin_success_updates_pin_and_audit(test_client) -> None:
    client, SessionLocal = test_client
    token, user_id = _register_and_login(client, "resetpin1@example.com", "1234")

    # 1. Reset PIN to 5678 with confirm_pin
    resp = client.post(
        "/api/v1/users/pin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "StrongPassword123!",
            "new_pin": "5678",
            "confirm_pin": "5678",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["transaction_pin_set"] is True
    assert "successfully" in data["message"].lower()

    # 2. Verify audit log entry
    with SessionLocal() as db:
        logs = db.query(AuditLog).filter(
            AuditLog.actor_user_id == user_id,
            AuditLog.action == "USER_PIN_UPDATE",
        ).all()
        assert len(logs) >= 1
        assert logs[-1].outcome == "SUCCESS"


def test_reset_pin_rejects_wrong_password(test_client) -> None:
    client, SessionLocal = test_client
    token, user_id = _register_and_login(client, "wrongpw@example.com", "1234")

    resp = client.post(
        "/api/v1/users/pin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "WrongPassword999!",
            "new_pin": "9999",
        },
    )
    assert resp.status_code == 401
    assert "password" in resp.json()["message"].lower()

    # Verify failed audit log
    with SessionLocal() as db:
        logs = db.query(AuditLog).filter(
            AuditLog.actor_user_id == user_id,
            AuditLog.action == "USER_PIN_UPDATE",
            AuditLog.outcome == "FAILURE",
        ).all()
        assert len(logs) == 1


def test_reset_pin_rejects_mismatched_confirmation(test_client) -> None:
    client, _ = test_client
    token, _ = _register_and_login(client, "mismatch@example.com", "1234")

    resp = client.post(
        "/api/v1/users/pin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "StrongPassword123!",
            "new_pin": "123456",
            "confirm_pin": "654321",
        },
    )
    assert resp.status_code == 422


def test_reset_pin_rejects_invalid_pin_format(test_client) -> None:
    client, _ = test_client
    token, _ = _register_and_login(client, "badformat@example.com", "1234")

    # Non-numeric
    resp1 = client.post(
        "/api/v1/users/pin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "StrongPassword123!",
            "new_pin": "abcd",
        },
    )
    assert resp1.status_code == 422

    # Too short (< 4 digits)
    resp2 = client.post(
        "/api/v1/users/pin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "StrongPassword123!",
            "new_pin": "123",
        },
    )
    assert resp2.status_code == 422

    # Too long (> 6 digits)
    resp3 = client.post(
        "/api/v1/users/pin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "StrongPassword123!",
            "new_pin": "1234567",
        },
    )
    assert resp3.status_code == 422


def test_reset_pin_supports_me_alias_and_legacy_fields(test_client) -> None:
    client, _ = test_client
    token, _ = _register_and_login(client, "alias@example.com", "1234")

    resp = client.post(
        "/api/v1/users/me/pin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "password": "StrongPassword123!",
            "pin": "654321",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["transaction_pin_set"] is True


def test_reset_pin_enables_subsequent_challenge_verification_with_new_pin(test_client) -> None:
    client, _ = test_client
    token, user_id = _register_and_login(client, "e2e@example.com", "1111")

    # Change PIN to 987654
    resp = client.post(
        "/api/v1/users/pin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "StrongPassword123!",
            "new_pin": "987654",
            "confirm_pin": "987654",
        },
    )
    assert resp.status_code == 200

    # Request an approval challenge
    ch_resp = client.post(
        "/api/v1/approvals/challenges",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "action": "BENEFICIARY_CREATE",
            "payload_hash": "a" * 64,
        },
    )
    assert ch_resp.status_code == 201
    ch_id = ch_resp.json()["challenge_id"]

    # Old PIN fails
    fail_verify = client.post(
        f"/api/v1/approvals/challenges/{ch_id}/verify",
        headers={"Authorization": f"Bearer {token}"},
        json={"pin": "1111"},
    )
    assert fail_verify.status_code == 401
    assert fail_verify.json()["error_code"] == "INVALID_PIN"

    # New PIN succeeds
    succ_verify = client.post(
        f"/api/v1/approvals/challenges/{ch_id}/verify",
        headers={"Authorization": f"Bearer {token}"},
        json={"pin": "987654"},
    )
    assert succ_verify.status_code == 200
    assert "approval_token" in succ_verify.json()
    assert len(succ_verify.json()["approval_token"]) > 10
