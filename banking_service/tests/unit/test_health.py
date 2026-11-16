"""Tests for the /health endpoint and X-Request-ID middleware (T1.3)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    def test_returns_200(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_returns_ok_status(self) -> None:
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_returns_service_name(self) -> None:
        response = client.get("/health")
        data = response.json()
        assert data["service"] == "banking"

    def test_response_has_request_id_header(self) -> None:
        response = client.get("/health")
        assert "x-request-id" in response.headers

    def test_custom_request_id_echoed(self) -> None:
        response = client.get("/health", headers={"X-Request-ID": "my-trace-id-123"})
        assert response.headers["x-request-id"] == "my-trace-id-123"

    def test_missing_request_id_generates_uuid(self) -> None:
        response = client.get("/health")
        rid = response.headers.get("x-request-id", "")
        # UUIDs are 36 chars: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        assert len(rid) == 36
        assert rid.count("-") == 4
