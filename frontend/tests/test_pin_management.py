"""Tests for Transaction PIN management (signup PIN and PIN regeneration) in the frontend."""
from __future__ import annotations

import httpx
import pytest

from clients.banking_client import BankingAPIError, BankingClient


class TestBankingClientPinMethods:
    def test_register_with_pin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_payload = {}

        def mock_post(self, url, **kwargs):
            nonlocal captured_payload
            captured_payload = kwargs.get("json", {})
            return httpx.Response(
                201,
                json={
                    "id": "u-123",
                    "email": "pinuser@example.com",
                    "phone": "+919876543210",
                    "full_name": "PIN User",
                    "transaction_pin_set": True,
                    "created_at": "2026-11-18T10:00:00Z",
                },
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://banking-service")

        res = client.register(
            email="pinuser@example.com",
            phone="+919876543210",
            full_name="PIN User",
            password="StrongPassword123!",
            pin="1234",
        )
        assert res["transaction_pin_set"] is True
        assert captured_payload["pin"] == "1234"
        assert captured_payload["email"] == "pinuser@example.com"

    def test_register_without_pin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_payload = {}

        def mock_post(self, url, **kwargs):
            nonlocal captured_payload
            captured_payload = kwargs.get("json", {})
            return httpx.Response(
                422,
                json={
                    "error_code": "INVALID_PIN_FORMAT",
                    "message": "Transaction PIN is required and must be 4 to 6 numeric digits",
                },
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://banking-service")

        with pytest.raises(BankingAPIError) as exc_info:
            client.register(
                email="nopin@example.com",
                phone="+919876543210",
                full_name="No PIN User",
                password="StrongPassword123!",
                pin=None,
            )
        assert exc_info.value.status_code == 422
        assert "pin" not in captured_payload

    def test_set_transaction_pin_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_payload = {}
        captured_headers = {}

        def mock_post(self, url, **kwargs):
            nonlocal captured_payload, captured_headers
            captured_payload = kwargs.get("json", {})
            captured_headers = kwargs.get("headers", {})
            return httpx.Response(
                200,
                json={
                    "message": "Transaction PIN updated successfully",
                    "transaction_pin_set": True,
                },
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://banking-service")

        # 1. Test token first signature: set_transaction_pin(token, pwd, pin, confirm_pin)
        token = "header.payload.signature"
        res1 = client.set_transaction_pin(token, "StrongPassword123!", "5678", "5678")
        assert res1["transaction_pin_set"] is True
        assert captured_payload["current_password"] == "StrongPassword123!"
        assert captured_payload["new_pin"] == "5678"
        assert captured_payload["confirm_pin"] == "5678"
        assert captured_headers["Authorization"] == f"Bearer {token}"

        # 2. Test keyword signature: set_transaction_pin(access_token=..., current_password=..., new_pin=...)
        res2 = client.set_transaction_pin(
            access_token=token,
            current_password="StrongPassword123!",
            new_pin="987654",
        )
        assert res2["transaction_pin_set"] is True
        assert captured_payload["new_pin"] == "987654"

    def test_set_transaction_pin_wrong_password_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(
                401,
                json={
                    "error_code": "INVALID_CREDENTIALS",
                    "message": "Account password verification failed",
                },
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://banking-service")

        with pytest.raises(BankingAPIError) as exc_info:
            client.set_transaction_pin(
                access_token="header.payload.signature",
                current_password="WrongPassword123!",
                new_pin="1234",
            )
        assert exc_info.value.status_code == 401
        assert "password" in exc_info.value.message.lower()

    def test_set_transaction_pin_missing_arguments_raises(self) -> None:
        client = BankingClient("http://banking-service")
        with pytest.raises(ValueError):
            client.set_transaction_pin()
