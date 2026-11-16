"""Tests for the AI service /health endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    def test_health_returns_200(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_payload(self) -> None:
        response = client.get("/health")
        assert response.json() == {"status": "ok", "service": "ai"}
