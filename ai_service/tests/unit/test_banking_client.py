"""Contract-style tests for BankingClient against a mock banking server."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import AISettings
from app.integrations.banking_client import BankingClient, BankingClientError


@pytest.fixture
def settings() -> AISettings:
    return AISettings(
        AI_DATABASE_URL="sqlite:///./test.db",
        AI_SECRET_KEY="test-secret",
        AI_BANKING_SERVICE_URL="http://test-banking:8000",
        AI_SERVICE_KEY="test-service:test-key",
    )


@pytest.fixture
def client(settings: AISettings) -> BankingClient:
    return BankingClient(settings=settings, access_token="fake.jwt.token")


class TestBankingClientAccounts:
    def test_list_accounts_success(self, client: BankingClient) -> None:
        mock_response = [{"id": "acc-1", "account_number_masked": "XXXXXX1234"}]
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: mock_response
            )
            result = client.list_accounts()
            assert result == mock_response
            call_kwargs = mock_get.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert headers["Authorization"] == "Bearer fake.jwt.token"
            assert headers["X-Service-Key"] == "test-service:test-key"

    def test_get_account_not_found_raises(self, client: BankingClient) -> None:
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=404,
                is_success=False,
                json=lambda: {"error_code": "NOT_FOUND", "message": "Account not found"},
            )
            with pytest.raises(BankingClientError) as exc:
                client.get_account("nonexistent")
            assert exc.value.error_code == "NOT_FOUND"
            assert exc.value.http_status == 404

    def test_get_balance_success(self, client: BankingClient) -> None:
        mock_response = {"account_id": "acc-1", "balance_minor": 50000, "currency": "INR"}
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: mock_response
            )
            result = client.get_balance("acc-1")
            assert result["balance_minor"] == 50000

    def test_timeout_raises_banking_client_error(self, client: BankingClient) -> None:
        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(BankingClientError) as exc:
                client.list_accounts()
            assert exc.value.error_code == "TIMEOUT"
            assert exc.value.http_status == 504

    def test_retry_on_500_then_success(self, client: BankingClient) -> None:
        fail_resp = MagicMock(status_code=500, is_success=False)
        ok_resp = MagicMock(status_code=200, is_success=True, json=lambda: [{"id": "acc-1"}])
        with patch("httpx.get", side_effect=[fail_resp, ok_resp]):
            result = client.list_accounts()
            assert len(result) == 1
            assert result[0]["id"] == "acc-1"

    def test_retry_exhausted_raises(self, client: BankingClient) -> None:
        fail_resp = MagicMock(
            status_code=503,
            is_success=False,
            json=lambda: {"error_code": "UNAVAILABLE", "message": "Service unavailable"},
        )
        with patch("httpx.get", return_value=fail_resp):
            with pytest.raises(BankingClientError) as exc:
                client.list_accounts()
            assert exc.value.http_status == 503


class TestBankingClientBeneficiaries:
    def test_list_beneficiaries(self, client: BankingClient) -> None:
        mock_response = [{"id": "bene-1", "name": "Alice"}]
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: mock_response
            )
            result = client.list_beneficiaries(q="Alice")
            assert result == mock_response
            assert mock_get.call_args.kwargs["params"] == {"q": "Alice"}

    def test_create_beneficiary_sends_approval_token(self, client: BankingClient) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=201, is_success=True, json=lambda: {"id": "bene-1"}
            )
            res = client.create_beneficiary({"name": "Bob"}, "approval-tok-123")
            assert res["id"] == "bene-1"
            headers = mock_post.call_args.kwargs["headers"]
            assert headers["X-Approval-Token"] == "approval-tok-123"


class TestBankingClientTransfers:
    def test_prepare_transfer_sends_idempotency_key(self, client: BankingClient) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=201,
                is_success=True,
                json=lambda: {"id": "txn-1", "status": "PENDING_APPROVAL"},
            )
            result = client.prepare_transfer({"amount_minor": 10000}, "idem-key-1")
            assert result["id"] == "txn-1"
            call_kwargs = mock_post.call_args
            assert "Idempotency-Key" in call_kwargs.kwargs.get("headers", {})
            assert call_kwargs.kwargs["headers"]["Idempotency-Key"] == "idem-key-1"

    def test_execute_transfer_sends_auth_and_hash(self, client: BankingClient) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: {"id": "txn-1", "status": "COMPLETED"}
            )
            result = client.execute_transfer(
                txn_id="txn-1",
                authorization_id="auth-1",
                summary_hash="hash-123",
                idempotency_key="idem-exec-1",
            )
            assert result["status"] == "COMPLETED"
            call_kwargs = mock_post.call_args
            assert call_kwargs.kwargs["json"] == {
                "authorization_id": "auth-1",
                "summary_hash": "hash-123",
            }
            assert call_kwargs.kwargs["headers"]["Idempotency-Key"] == "idem-exec-1"

    def test_cancel_transfer_success(self, client: BankingClient) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=204, is_success=True)
            res = client.cancel_transfer("txn-1")
            assert res is None

    def test_get_transfer_limits(self, client: BankingClient) -> None:
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: {"daily_limit_minor": 5000000}
            )
            res = client.get_transfer_limits()
            assert res["daily_limit_minor"] == 5000000


class TestBankingClientLoansAndCards:
    def test_loans_endpoints(self, client: BankingClient) -> None:
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: [{"id": "loan-offer-1"}]
            )
            offers = client.list_loan_offers()
            assert len(offers) == 1

        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: {"eligible": True}
            )
            elig = client.check_loan_eligibility({"monthly_income_minor": 10000000})
            assert elig["eligible"] is True

    def test_cards_endpoints(self, client: BankingClient) -> None:
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: [{"id": "card-1"}]
            )
            cards = client.list_cards()
            assert len(cards) == 1

        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: {"status": "SUCCESS"}
            )
            res = client.execute_card_payment("pay-1", "auth-9", "idem-pay-1")
            assert res["status"] == "SUCCESS"


class TestBankingClientUser:
    def test_get_user_profile(self, client: BankingClient) -> None:
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: {"id": "u-1", "email": "test@bank.com"}
            )
            profile = client.get_user_profile()
            assert profile["email"] == "test@bank.com"

    def test_base_url_normalization_with_api_v1_suffix(self, settings: AISettings) -> None:
        settings_with_suffix = AISettings(
            AI_BANKING_SERVICE_URL="http://test-banking:8000/api/v1",
            AI_DATABASE_URL="sqlite:///:memory:",
            AI_SERVICE_KEY="test-key",
            AI_SECRET_KEY="test-secret-key-32-chars-minimum-len",
        )
        client = BankingClient(settings=settings_with_suffix, access_token="token")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, is_success=True, json=lambda: [{"id": "acc-1"}]
            )
            accounts = client.list_accounts()
            assert len(accounts) == 1
            # Ensure URL does not contain duplicate /api/v1/api/v1
            called_url = mock_get.call_args[0][0]
            assert called_url == "http://test-banking:8000/api/v1/accounts"
