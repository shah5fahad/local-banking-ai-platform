"""Unit tests for Direct Banking UI and BankingClient direct banking methods (T6.6)."""
from __future__ import annotations

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from clients.banking_client import BankingClient


class TestBankingClientDirectBanking:
    def test_list_and_add_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "acc-1",
                        "user_id": "u-1",
                        "holder_name": "Alice C.",
                        "account_number_masked": "XXXXXX1234",
                        "account_number_last4": "1234",
                        "ifsc": "HDFC0001234",
                        "bank_name": "HDFC Bank",
                        "branch_name": "Main Branch",
                        "account_type": "SAVINGS",
                        "balance_minor": 5000000,
                        "currency": "INR",
                        "verification_status": "VERIFIED",
                        "status": "ACTIVE",
                        "created_at": "2026-11-10T00:00:00Z",
                    }
                ],
            )

        def mock_post(self, url, **kwargs):
            payload = kwargs.get("json", {})
            return httpx.Response(
                201,
                json={
                    "id": "acc-new",
                    "user_id": "u-1",
                    "holder_name": payload.get("holder_name"),
                    "account_number_masked": "XXXXXX9999",
                    "account_number_last4": "9999",
                    "ifsc": payload.get("ifsc"),
                    "bank_name": payload.get("bank_name"),
                    "branch_name": payload.get("branch_name"),
                    "account_type": payload.get("account_type"),
                    "balance_minor": 0,
                    "currency": "INR",
                    "verification_status": "PENDING",
                    "status": "ACTIVE",
                    "created_at": "2026-11-11T12:00:00Z",
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        monkeypatch.setattr(httpx.Client, "post", mock_post)

        client = BankingClient("http://banking-service")
        accounts = client.list_accounts("token-123")
        assert len(accounts) == 1
        assert accounts[0]["account_number_masked"] == "XXXXXX1234"

        new_acc = client.add_account(
            {
                "holder_name": "Alice C.",
                "account_number": "123456789999",
                "ifsc": "SBIN0001234",
                "bank_name": "State Bank of India",
                "branch_name": "Connaught Place",
                "account_type": "SAVINGS",
            },
            "token-123",
        )
        assert new_acc["id"] == "acc-new"
        assert new_acc["bank_name"] == "State Bank of India"

    def test_get_account_balance_and_verify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "available_minor": 7500000,
                    "currency": "INR",
                    "as_of": "2026-11-11T12:00:00Z",
                },
            )

        def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "verification_status": "VERIFIED",
                    "message": "Account verification completed: VERIFIED",
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        monkeypatch.setattr(httpx.Client, "post", mock_post)

        client = BankingClient("http://banking-service")
        bal = client.get_account_balance("acc-1", "token-123")
        assert bal["available_minor"] == 7500000

        ver = client.verify_account("acc-1", "token-123")
        assert ver["verification_status"] == "VERIFIED"

    def test_deactivate_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_delete(self, url, **kwargs):
            return httpx.Response(204)

        monkeypatch.setattr(httpx.Client, "delete", mock_delete)
        client = BankingClient("http://banking-service")
        assert client.deactivate_account("acc-1", "token-123") is True

    def test_list_and_create_beneficiary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "bene-1",
                        "user_id": "u-1",
                        "name": "Bob Friend",
                        "nickname": "Bob",
                        "account_number_masked": "XXXXXX5678",
                        "account_number_last4": "5678",
                        "ifsc": "ICIC0001234",
                        "bank_name": "ICICI Bank",
                        "verification_status": "VERIFIED",
                        "status": "ACTIVE",
                        "created_at": "2026-11-10T10:00:00Z",
                    }
                ],
            )

        def mock_post(self, url, **kwargs):
            payload = kwargs.get("json", {})
            headers = kwargs.get("headers", {})
            assert headers.get("X-Approval-Token") == "appr-token-xyz"
            return httpx.Response(
                201,
                json={
                    "id": "bene-new",
                    "user_id": "u-1",
                    "name": payload.get("name"),
                    "account_number_masked": "XXXXXX7777",
                    "ifsc": payload.get("ifsc"),
                    "bank_name": payload.get("bank_name"),
                    "verification_status": "VERIFIED",
                    "status": "ACTIVE",
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        monkeypatch.setattr(httpx.Client, "post", mock_post)

        client = BankingClient("http://banking-service")
        benes = client.list_beneficiaries("token-123")
        assert len(benes) == 1
        assert benes[0]["name"] == "Bob Friend"

        created = client.create_beneficiary(
            {
                "name": "Charlie Colleague",
                "account_number": "123456787777",
                "ifsc": "HDFC0004321",
                "bank_name": "HDFC Bank",
            },
            approval_token="appr-token-xyz",
            access_token="token-123",
        )
        assert created["id"] == "bene-new"

    def test_verify_and_deactivate_beneficiary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "verification_status": "VERIFIED",
                    "message": "Beneficiary verified",
                },
            )

        def mock_delete(self, url, **kwargs):
            return httpx.Response(204)

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        monkeypatch.setattr(httpx.Client, "delete", mock_delete)

        client = BankingClient("http://banking-service")
        ver = client.verify_beneficiary("bene-1", "token-123")
        assert ver["verification_status"] == "VERIFIED"

        assert client.deactivate_beneficiary("bene-1", "token-123") is True

    def test_list_and_get_transaction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            if "/by-reference/" in url:
                return httpx.Response(200, json={"id": "t-1", "reference": "TXN9999", "status": "COMPLETED"})
            if "/transactions/" in url:
                return httpx.Response(200, json={"id": "t-1", "reference": "TXN9999", "status": "COMPLETED"})
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "t-1",
                            "reference": "TXN9999",
                            "user_id": "u-1",
                            "type": "TRANSFER",
                            "amount_minor": 100000,
                            "fee_minor": 0,
                            "total_debit_minor": 100000,
                            "currency": "INR",
                            "status": "COMPLETED",
                            "channel": "IMPS",
                            "source_account_masked": "XXXXXX1234",
                            "created_at": "2026-11-11T12:00:00Z",
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 50,
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://banking-service")
        txns = client.list_transactions("token-123")
        assert txns["total"] == 1
        assert txns["items"][0]["reference"] == "TXN9999"

        single = client.get_transaction("t-1", "token-123")
        assert single["reference"] == "TXN9999"

        by_ref = client.get_transaction_by_reference("TXN9999", "token-123")
        assert by_ref["status"] == "COMPLETED"


class TestDirectBankingAppTest:
    def test_direct_banking_blocks_unauthenticated(self) -> None:
        """Route guard require_auth blocks unauthenticated sessions."""
        at = AppTest.from_file("../pages/5_Banking.py", default_timeout=10)
        at.session_state["authenticated"] = False
        at.session_state["user"] = None
        at.session_state["access_token"] = None

        at.run()
        # Should prompt with authentication required warning
        assert any("Authentication Required" in w.value for w in at.warning)

    def test_direct_banking_renders_for_customer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Authenticated customer can view 3 tabs, accounts, and transactions."""
        def mock_get(self, url, **kwargs):
            if "/accounts" in url:
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "acc-10",
                            "user_id": "cust-1",
                            "holder_name": "Alice Customer",
                            "account_number_masked": "XXXXXX4321",
                            "account_number_last4": "4321",
                            "ifsc": "HDFC0001234",
                            "bank_name": "HDFC Bank",
                            "branch_name": "Cyber City",
                            "account_type": "SAVINGS",
                            "balance_minor": 15000000,
                            "currency": "INR",
                            "verification_status": "VERIFIED",
                            "status": "ACTIVE",
                            "created_at": "2026-11-10T10:00:00Z",
                        }
                    ],
                )
            if "/beneficiaries" in url:
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "bene-20",
                            "user_id": "cust-1",
                            "name": "Bob Recipient",
                            "account_number_masked": "XXXXXX9876",
                            "ifsc": "SBIN0001234",
                            "bank_name": "State Bank of India",
                            "verification_status": "VERIFIED",
                            "status": "ACTIVE",
                        }
                    ],
                )
            if "/transactions" in url:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": "t-100",
                                "reference": "TXN123456",
                                "type": "TRANSFER",
                                "amount_minor": 500000,
                                "fee_minor": 500,
                                "total_debit_minor": 500500,
                                "status": "COMPLETED",
                                "source_account_masked": "XXXXXX4321",
                                "created_at": "2026-11-11T11:00:00Z",
                            }
                        ],
                        "total": 1,
                        "page": 1,
                        "page_size": 100,
                    },
                )
            return httpx.Response(200, json={})

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        at = AppTest.from_file("../pages/5_Banking.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "cust-1",
            "full_name": "Alice Customer",
            "email": "alice@bank.local",
            "roles": ["CUSTOMER"],
        }
        at.session_state["roles"] = ["CUSTOMER"]
        at.session_state["access_token"] = "valid-cust-token"

        at.run()
        assert not at.exception
        # Title check
        assert any("Direct Banking" in t.value for t in at.title)
        # 3 Tabs check
        assert len(at.tabs) == 3
        # Account details check
        assert any("HDFC Bank" in md.value for md in at.markdown)
        assert any(m.label == "Available Balance" for m in at.metric)
