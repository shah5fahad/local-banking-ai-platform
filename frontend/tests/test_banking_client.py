"""Unit tests for frontend BankingClient and validation helpers."""
from __future__ import annotations

import httpx
import pytest

from clients.banking_client import BankingAPIError, BankingClient


class TestBankingClientValidation:
    def test_password_complexity_valid(self) -> None:
        errors = BankingClient.validate_password_complexity("StrongP@ssw0rd!")
        assert errors == []

    def test_password_complexity_missing_requirements(self) -> None:
        # Too short
        assert any("12 characters" in e for e in BankingClient.validate_password_complexity("Short1!"))
        # Missing uppercase
        assert any("uppercase" in e for e in BankingClient.validate_password_complexity("lowercase123!@#"))
        # Missing lowercase
        assert any("lowercase" in e for e in BankingClient.validate_password_complexity("UPPERCASE123!@#"))
        # Missing number
        assert any("number" in e for e in BankingClient.validate_password_complexity("NoNumbersHere!@#"))
        # Missing special
        assert any("special" in e for e in BankingClient.validate_password_complexity("NoSpecialChars123"))

    def test_phone_validation(self) -> None:
        assert BankingClient.validate_phone("+919876543210") is True
        assert BankingClient.validate_phone("9876543210") is True
        assert BankingClient.validate_phone("+14155552671") is True
        # Invalid
        assert BankingClient.validate_phone("123") is False
        assert BankingClient.validate_phone("abcdefghij") is False
        assert BankingClient.validate_phone("+123456789012345678") is False  # > 15 digits


class TestBankingClientApiMethods:
    def test_register_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(201, json={"id": "usr-1", "email": "test@example.com", "full_name": "Test"})

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://testserver")
        result = client.register("test@example.com", "+919876543210", "Test", "P@ssword1234!")
        assert result["id"] == "usr-1"

    def test_register_error_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(409, json={"message": "An account with this email already exists", "error_code": "CONFLICT"})

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://testserver")
        with pytest.raises(BankingAPIError) as exc:
            client.register("test@example.com", "+919876543210", "Test", "P@ssword1234!")
        assert exc.value.status_code == 409
        assert "already exists" in exc.value.message

    def test_login_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(200, json={"access_token": "acc-tok", "refresh_token": "ref-tok", "token_type": "bearer"})

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://testserver")
        tokens = client.login("test@example.com", "Password123!")
        assert tokens["access_token"] == "acc-tok"
        assert tokens["refresh_token"] == "ref-tok"

    def test_refresh_token_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(200, json={"access_token": "new-acc", "refresh_token": "new-ref"})

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://testserver")
        tokens = client.refresh("old-ref")
        assert tokens["access_token"] == "new-acc"

    def test_get_me_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(200, json={"id": "usr-1", "email": "test@example.com", "roles": ["CUSTOMER"]})

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://testserver")
        user = client.get_me("dummy-token")
        assert user["email"] == "test@example.com"
        assert "CUSTOMER" in user["roles"]

    def test_logout_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(200, json={"message": "Logged out successfully"})

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = BankingClient("http://testserver")
        result = client.logout("dummy-token")
        assert result["message"] == "Logged out successfully"
