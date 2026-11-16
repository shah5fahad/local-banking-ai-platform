"""Unit tests for Chat page components, direct PIN submission security invariant, citations, and approval cards."""
from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from clients.banking_client import BankingClient
from components.approval_card import render_approval_card
from components.citations import render_citations
from components.pin_dialog import submit_direct_pin_authorization
from state.session import init_session, login_user


class TestDirectPinSecurityInvariant:
    """Verify that PIN authorization calls the Core Banking Service directly and never traverses AI."""

    def test_transfer_direct_pin_authorization(self) -> None:
        mock_banking = MagicMock(spec=BankingClient)
        mock_banking.create_transfer_challenge.return_value = {"challenge_id": "chal-123", "method": "PIN"}
        mock_banking.authorize_transfer.return_value = {"authorization_id": "auth-789", "status": "AUTHORIZED"}

        auth_id = submit_direct_pin_authorization(
            workflow="TRANSFER",
            banking_resource_id="txn-456",
            pin="1234",
            approval_id="appr-001",
            summary_hash="hash-xyz",
            banking_client=mock_banking,
            access_token="bearer-token",
        )

        assert auth_id == "auth-789"
        # Verify direct banking calls
        mock_banking.create_transfer_challenge.assert_called_once_with(
            txn_id="txn-456",
            access_token="bearer-token",
        )
        mock_banking.authorize_transfer.assert_called_once_with(
            txn_id="txn-456",
            challenge_id="chal-123",
            pin="1234",
            access_token="bearer-token",
        )

    def test_card_payment_direct_pin_authorization(self) -> None:
        mock_banking = MagicMock(spec=BankingClient)
        mock_banking.authorize_card_payment.return_value = {"id": "pay-123", "status": "AUTHORIZED"}

        auth_id = submit_direct_pin_authorization(
            workflow="CARD_PAYMENT",
            banking_resource_id="pay-123",
            pin="9999",
            approval_id="appr-002",
            summary_hash="hash-card",
            banking_client=mock_banking,
            access_token="bearer-token",
        )

        assert auth_id == "pay-123"
        mock_banking.authorize_card_payment.assert_called_once_with(
            payment_id="pay-123",
            pin="9999",
            access_token="bearer-token",
        )

    def test_beneficiary_direct_pin_authorization(self) -> None:
        mock_banking = MagicMock(spec=BankingClient)
        mock_banking.create_beneficiary_challenge.return_value = {"challenge_id": "bene-chal-1"}
        mock_banking.verify_beneficiary_challenge.return_value = {"approval_token": "token-bene-approved"}

        auth_id = submit_direct_pin_authorization(
            workflow="BENEFICIARY",
            banking_resource_id="bene-draft-1",
            pin="4321",
            approval_id="appr-003",
            summary_hash="hash-bene",
            banking_client=mock_banking,
            access_token="bearer-token",
        )

        assert auth_id == "token-bene-approved"
        mock_banking.create_beneficiary_challenge.assert_called_once_with(
            action="BENEFICIARY_CREATE",
            payload_hash="hash-bene",
            access_token="bearer-token",
        )
        mock_banking.verify_beneficiary_challenge.assert_called_once_with(
            challenge_id="bene-chal-1",
            pin="4321",
            access_token="bearer-token",
        )


class TestCitationsComponent:
    def test_render_citations_noop_on_empty(self) -> None:
        # Should not raise exception
        render_citations([])

    def test_render_citations_content(self) -> None:
        citations = [
            {
                "title": "RBI Master Direction on KYC 2024",
                "section": "Chapter 3",
                "score": 0.88,
                "excerpt": "A customer identification procedure must be carried out...",
            },
            {
                "title": "NPCI Unified Payments Interface Rules",
                "section": "Section 4.2",
                "score": 0.75,
                "excerpt": "Per-transaction limit is capped at ₹1,00,000 for standard categories.",
            },
        ]
        # Verify callable without exceptions
        render_citations(citations)


class TestChatPageAppTest:
    def test_chat_page_authenticated_renders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify 1_Chat.py boots and displays title, chat input, and empty chat state."""
        def mock_get(self, url, **kwargs):
            return httpx.Response(200, json={"id": "conv-1", "title": "Account Balance Chat", "messages": []})

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        at = AppTest.from_file("../pages/1_Chat.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "usr-1",
            "full_name": "Bob Johnson",
            "email": "bob@bank.local",
            "roles": ["CUSTOMER"],
        }
        at.session_state["roles"] = ["CUSTOMER"]
        at.session_state["access_token"] = "valid-token"
        at.session_state["active_conversation_id"] = "conv-1"
        at.session_state["chat_messages"] = [
            {"role": "user", "content": "Hello, what is my account balance?"},
            {"role": "assistant", "content": "Your savings account balance is ₹45,000.00."},
        ]

        at.run()
        assert not at.exception
        # Chat title rendered
        assert any("Account Balance Chat" in t.value or "AI Banking Assistant" in t.value for t in at.title)
        # Chat input element exists
        assert len(at.chat_input) >= 1

    def test_chat_page_with_pending_approval_renders_card(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify 1_Chat.py renders the HITL approval card when an approval is pending."""
        def mock_get(self, url, **kwargs):
            return httpx.Response(200, json={"items": []})

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        at = AppTest.from_file("../pages/1_Chat.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {"id": "usr-1", "full_name": "Bob", "roles": ["CUSTOMER"]}
        at.session_state["roles"] = ["CUSTOMER"]
        at.session_state["access_token"] = "valid-token"
        at.session_state["pending_approval"] = {
            "approval_id": "appr-100",
            "workflow": "TRANSFER",
            "status": "PENDING",
            "risk_level": "FINANCIAL",
            "summary": {
                "beneficiary": "Alice Smith",
                "account_masked": "XXXXXX5678",
                "amount": "₹10,000.00",
                "total_debit": "₹10,005.00",
            },
            "expires_at": "2030-01-01T12:00:00Z",
        }

        at.run()
        assert not at.exception
        # Action required header rendered
        subheaders = [s.value for s in at.subheader]
        assert any("Fund Transfer Confirmation" in sh for sh in subheaders)
        # Confirm and Reject buttons exist
        button_labels = [b.label for b in at.button]
        assert any("Confirm" in lbl for lbl in button_labels)
        assert any("Reject" in lbl for lbl in button_labels)
