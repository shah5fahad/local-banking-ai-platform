"""Unit and component tests for Customer Dashboard (T7.4)."""
from __future__ import annotations

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from clients.banking_client import BankingClient


class TestCustomerDashboardClientMethods:
    def test_get_customer_dashboard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, headers=None, **kwargs):
            return httpx.Response(
                200,
                json={
                    "user": {"id": "usr-1", "email": "test@bank.local", "full_name": "Test User", "roles": ["CUSTOMER"]},
                    "accounts": [
                        {
                            "id": "acc-1",
                            "bank_name": "Local Bank",
                            "account_number_masked": "XXXXXX1234",
                            "balance_minor": 10_000_000,
                            "status": "ACTIVE",
                            "verification_status": "VERIFIED",
                        }
                    ],
                    "cards": [
                        {
                            "id": "card-1",
                            "network": "VISA",
                            "last4": "4321",
                            "card_number_masked": "XXXX-XXXX-XXXX-4321",
                            "credit_limit_minor": 20_000_000,
                            "outstanding_minor": 0,
                            "status": "ACTIVE",
                        }
                    ],
                    "loan_offers": [
                        {
                            "id": "loan-1",
                            "loan_type": "HOME",
                            "name": "Pre-Approved Home Loan",
                            "max_amount_minor": 500_000_000,
                            "rate_bps": 850,
                            "min_tenure_months": 60,
                            "max_tenure_months": 240,
                            "status": "ACTIVE",
                        }
                    ],
                    "total_balance_minor": 10_000_000,
                    "total_credit_limit_minor": 20_000_000,
                    "total_available_credit_minor": 20_000_000,
                    "as_of": "2026-11-16T00:00:00Z",
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://testserver")
        dash = client.get_customer_dashboard("fake_token")
        assert dash["user"]["full_name"] == "Test User"
        assert len(dash["accounts"]) == 1
        assert len(dash["cards"]) == 1
        assert len(dash["loan_offers"]) == 1
        assert dash["total_balance_minor"] == 10_000_000

    def test_list_credit_cards(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, headers=None, **kwargs):
            return httpx.Response(
                200,
                json=[{"id": "c-1", "network": "VISA", "last4": "1234", "status": "ACTIVE"}],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://testserver")
        cards = client.list_credit_cards("fake_token")
        assert len(cards) == 1
        assert cards[0]["network"] == "VISA"

    def test_get_card_sensitive_details(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, headers=None, **kwargs):
            return httpx.Response(
                200,
                json={
                    "card_id": "c-1",
                    "card_number": "4123456789012345",
                    "expiry_date": "12/29",
                    "cvv": "789",
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://testserver")
        details = client.get_card_sensitive_details("c-1", "fake_token")
        assert details["card_number"] == "4123456789012345"
        assert details["cvv"] == "789"

    def test_list_loan_offers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, headers=None, **kwargs):
            return httpx.Response(
                200,
                json=[
                    {"id": "l-1", "loan_type": "HOME", "status": "ACTIVE"},
                    {"id": "l-2", "loan_type": "AUTO", "status": "ACTIVE"},
                    {"id": "l-3", "loan_type": "PERSONAL", "status": "ACTIVE"},
                ],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://testserver")
        offers = client.list_loan_offers("fake_token")
        assert len(offers) == 3


def test_customer_dashboard_rendered_in_app() -> None:
    """Ensure app.py renders financial metrics and tabs for accounts, cards, and loan offers."""
    at = AppTest.from_file("../app.py", default_timeout=10)
    at.session_state["authenticated"] = True
    at.session_state["user"] = {
        "id": "u-test",
        "full_name": "Priya Sharma",
        "email": "priya@bank.local",
        "roles": ["CUSTOMER"],
    }
    at.session_state["roles"] = ["CUSTOMER"]
    at.session_state["access_token"] = "mock_token"
    at.run()

    assert not at.exception
    # Check title
    assert any("Priya Sharma" in t.value for t in at.title)

    # Check financial metrics rendered
    metric_labels = [m.label for m in at.metric]
    assert "Total Bank Balance" in metric_labels
    assert "Total Credit Limit" in metric_labels
    assert "Available Card Limit" in metric_labels
    assert "Pre-Approved Loans" in metric_labels

    # Check tabs for accounts, credit cards, loan offers exist
    tab_labels = [t.label for t in at.tabs]
    assert any("Bank Accounts" in lbl for lbl in tab_labels)
    assert any("Credit Cards" in lbl for lbl in tab_labels)
    assert any("Loan Offers" in lbl for lbl in tab_labels)
