"""Unit tests for the Banking Ops node and READ tools (T4.1)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from app.agents.nodes.banking_ops import banking_ops_node
from app.agents.state import GraphState
from app.agents.tools.registry import get_registry
from app.integrations.llm_factory import FakeChatModel, set_test_fake_llm


def test_banking_ops_node_fallback_accounts() -> None:
    """Test banking_ops_node fallback when LLM produces no tool calls."""
    state: GraphState = {
        "intent": "BANK_READ",
        "user_message": "What is my account balance?",
        "messages": [],
    }
    config = {"configurable": {"access_token": "valid-jwt-token"}}

    mock_client = MagicMock()
    mock_client.list_accounts.return_value = [
        {
            "id": "acc-1",
            "bank_name": "Test Bank",
            "account_type": "SAVINGS",
            "account_number_masked": "XXXXXX1234",
            "account_number_last4": "1234",
            "verification_status": "VERIFIED",
            "status": "ACTIVE",
        }
    ]

    with patch("app.agents.nodes.banking_ops.BankingClient", return_value=mock_client):
        result = banking_ops_node(state, config=config)

    assert "tool_results" in result
    assert len(result["tool_results"]) >= 1
    tool_res = result["tool_results"][0]
    assert tool_res["tool_name"] == "list_accounts"
    assert tool_res["success"] is True

    parsed_data = json.loads(tool_res["result_masked"])
    assert "accounts" in parsed_data
    assert parsed_data["accounts"][0]["account_number_masked"] == "XXXXXX1234"


def test_banking_ops_node_fallback_transactions() -> None:
    """Test banking_ops_node fallback for transaction queries."""
    state: GraphState = {
        "intent": "BANK_READ",
        "user_message": "Show my last 10 transactions",
        "messages": [],
    }
    config = {"configurable": {"access_token": "valid-jwt-token"}}

    mock_client = MagicMock()
    mock_client.list_transactions.return_value = {
        "items": [
            {
                "id": "txn-1",
                "reference": "TXN123",
                "amount_minor": 500000,
                "type": "DEBIT",
                "status": "COMPLETED",
            }
        ],
        "total": 1,
    }

    with patch("app.agents.nodes.banking_ops.BankingClient", return_value=mock_client):
        result = banking_ops_node(state, config=config)

    tool_res = result["tool_results"][0]
    assert tool_res["tool_name"] == "list_transactions"
    assert tool_res["success"] is True


def test_banking_ops_node_fallback_loan_offers() -> None:
    """Test banking_ops_node fallback for loan info queries."""
    state: GraphState = {
        "intent": "LOAN_INFO",
        "user_message": "Show my pre-approved loans",
        "messages": [],
    }
    config = {"configurable": {"access_token": "valid-jwt-token"}}

    mock_client = MagicMock()
    mock_client.list_loan_offers.return_value = [
        {"id": "offer-1", "loan_type": "PERSONAL", "max_amount_minor": 50000000}
    ]

    with patch("app.agents.nodes.banking_ops.BankingClient", return_value=mock_client):
        result = banking_ops_node(state, config=config)

    tool_res = result["tool_results"][0]
    assert tool_res["tool_name"] == "list_loan_offers"
    assert tool_res["success"] is True


def test_banking_ops_node_fallback_cards() -> None:
    """Test banking_ops_node fallback for credit cards."""
    state: GraphState = {
        "intent": "CARD_INFO",
        "user_message": "What are my credit card dues?",
        "messages": [],
    }
    config = {"configurable": {"access_token": "valid-jwt-token"}}

    mock_client = MagicMock()
    mock_client.get_card_outstanding.return_value = {
        "card_id": "card-1",
        "outstanding_minor": 1500000,
        "due_date": "2026-12-01",
    }
    mock_client.list_cards.return_value = [{"id": "card-1", "last4": "4321"}]

    with patch("app.agents.nodes.banking_ops.BankingClient", return_value=mock_client):
        result = banking_ops_node(state, config=config)

    tool_res = result["tool_results"][0]
    assert tool_res["success"] is True


def test_banking_ops_node_with_llm_tool_calls() -> None:
    """Test banking_ops_node when LLM invokes registered tools via tool_calls."""
    state: GraphState = {
        "intent": "BANK_READ",
        "user_message": "List my accounts please",
        "messages": [],
    }
    config = {"configurable": {"access_token": "valid-jwt-token"}}

    mock_client = MagicMock()
    mock_client.list_accounts.return_value = [
        {"id": "acc-100", "account_number_masked": "XXXXXX9999"}
    ]

    # Fake LLM returning a tool_call
    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "list_accounts", "args": {}, "id": "call_123"}],
    )
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value = fake_llm
    fake_llm.invoke.return_value = ai_msg

    with (
        patch("app.agents.nodes.banking_ops.create_llm", return_value=fake_llm),
        patch("app.agents.nodes.banking_ops.BankingClient", return_value=mock_client),
    ):
        result = banking_ops_node(state, config=config)

    assert len(result["tool_results"]) == 1
    assert result["tool_results"][0]["tool_name"] == "list_accounts"
    assert result["tool_results"][0]["success"] is True
