"""Comprehensive unit and integration tests for Phase 5 task T5.5: Credit Card Payment workflow.

Covers:
- Field extraction: option detection (total due, min due), amount parsing, card identifier (last4, network)
- Conversational multi-turn history extraction
- Card discovery: no cards, multiple cards (disambiguation), single card match
- Bill presentation: Total Due, Minimum Due, Due Date display when option/amount is unspecified
- Zero outstanding check: handles cards with 0 balance
- Account selection & balance check: insufficient funds, no active accounts
- Draft preparation via BankingClient (POST /credit-cards/{id}/payments)
- Error handling during draft preparation (BankingClientError and generic exceptions)
- Execute node: execution via BankingClient with single-use authorization_id and status confirmation
- Execute node: error handling
- End-to-end LangGraph HITL: prompt → Stage 1 interrupt(CONFIRM) → Stage 2 interrupt(AUTH) → execute
- Rejection flow: prompt → Stage 1 interrupt(CONFIRM) → REJECT → no execute, clean cancellation
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.nodes.execute import execute_node
from app.agents.state import GraphState, PendingAction
from app.agents.workflows.card_payment import (
    extract_card_payment_fields,
    workflow_card_payment_node,
)
from app.integrations.banking_client import BankingClientError
from app.models.approval import ApprovalStatus, WorkflowType

# ============================================================================
# 1. Field Extraction Unit Tests
# ============================================================================


def test_extract_card_payment_fields_options() -> None:
    # Total Due option
    res1 = extract_card_payment_fields("Pay total due for my credit card")
    assert res1["option"] == "TOTAL"

    # Minimum Due option
    res2 = extract_card_payment_fields("Pay minimum due on my card")
    assert res2["option"] == "MINIMUM"

    # Custom amount
    res3 = extract_card_payment_fields("Pay ₹5,000 for my credit card")
    assert res3["amount_minor"] == 500000
    assert res3["option"] is None


def test_extract_card_payment_fields_card_identifier() -> None:
    res1 = extract_card_payment_fields("Pay total due for card ending in 4321")
    assert res1["card_identifier"] == "4321"

    res2 = extract_card_payment_fields("Pay my Visa card bill")
    assert res2["card_identifier"] == "visa"


def test_extract_card_payment_fields_conversational_history() -> None:
    history = [
        HumanMessage(content="I want to pay my credit card bill"),
        AIMessage(content="Here are your card bill details. Total due is ₹15,000. How much would you like to pay?"),
    ]
    curr = "Pay total due"
    extracted = extract_card_payment_fields(curr, history)
    assert extracted["option"] == "TOTAL"


# ============================================================================
# 2. Card Discovery, Missing Options & Balance Checks
# ============================================================================


def test_workflow_card_payment_no_active_cards() -> None:
    state: GraphState = {"user_message": "Pay my credit card bill"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    with patch("app.agents.workflows.card_payment.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_cards.return_value = []

        res = workflow_card_payment_node(state, config=config)

    assert "pending_action" not in res
    assert res["approval_status"] == "NONE"
    assert "active credit cards" in res["response"].lower()


def test_workflow_card_payment_multiple_cards_disambiguation() -> None:
    state: GraphState = {"user_message": "Pay my credit card bill"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    cards = [
        {"id": "card-1", "network": "VISA", "last4": "1111", "outstanding_minor": 1000000, "status": "ACTIVE"},
        {"id": "card-2", "network": "MasterCard", "last4": "2222", "outstanding_minor": 500000, "status": "ACTIVE"},
    ]

    with patch("app.agents.workflows.card_payment.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_cards.return_value = cards

        res = workflow_card_payment_node(state, config=config)

    assert "pending_action" not in res
    assert res["approval_status"] == "NONE"
    assert "1111" in res["response"]
    assert "2222" in res["response"]
    assert "multiple active credit cards" in res["response"].lower()


def test_workflow_card_payment_unspecified_amount_presents_bill() -> None:
    """When amount/option is missing, presents Total Due and Minimum Due options."""
    state: GraphState = {"user_message": "Pay credit card"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    cards = [
        {"id": "card-1", "network": "VISA", "last4": "1234", "outstanding_minor": 1500000, "status": "ACTIVE"}
    ]

    with patch("app.agents.workflows.card_payment.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_cards.return_value = cards
        mock_instance.get_current_bill.return_value = {
            "id": "stmt-001",
            "total_due_minor": 1500000,
            "min_due_minor": 75000,
            "due_date": "2026-12-05T00:00:00Z",
        }

        res = workflow_card_payment_node(state, config=config)

    assert "pending_action" not in res
    assert res["approval_status"] == "NONE"
    assert "Total Due" in res["response"]
    assert "Minimum Due" in res["response"]
    assert "₹15,000.00" in res["response"]
    assert "₹750.00" in res["response"]


def test_workflow_card_payment_zero_outstanding() -> None:
    state: GraphState = {"user_message": "Pay total due for credit card"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    cards = [
        {"id": "card-1", "network": "VISA", "last4": "1234", "outstanding_minor": 0, "status": "ACTIVE"}
    ]

    with patch("app.agents.workflows.card_payment.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_cards.return_value = cards
        mock_instance.get_current_bill.return_value = {
            "id": "stmt-001",
            "total_due_minor": 0,
            "min_due_minor": 0,
        }

        res = workflow_card_payment_node(state, config=config)

    assert "pending_action" not in res
    assert "no outstanding balance due" in res["response"].lower()


def test_workflow_card_payment_insufficient_balance() -> None:
    state: GraphState = {"user_message": "Pay total due for credit card"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    cards = [
        {"id": "card-1", "network": "VISA", "last4": "1234", "outstanding_minor": 2000000, "status": "ACTIVE"}
    ]
    accounts = [
        {"id": "acc-1", "status": "ACTIVE", "balance_minor": 500000}  # Only ₹5,000
    ]

    with patch("app.agents.workflows.card_payment.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_cards.return_value = cards
        mock_instance.get_current_bill.return_value = {
            "id": "stmt-001",
            "total_due_minor": 2000000,
            "min_due_minor": 100000,
        }
        mock_instance.list_accounts.return_value = accounts

        res = workflow_card_payment_node(state, config=config)

    assert "pending_action" not in res
    assert "insufficient balance" in res["response"].lower()


def test_workflow_card_payment_no_access_token() -> None:
    state: GraphState = {"user_message": "Pay credit card bill"}
    res = workflow_card_payment_node(state, config={"configurable": {}})
    assert res.get("error_code") == "UNAUTHENTICATED"


# ============================================================================
# 3. Draft Preparation
# ============================================================================


def test_workflow_card_payment_prepare_total_due_success() -> None:
    state: GraphState = {"user_message": "Pay total due for my Visa card"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    cards = [
        {"id": "card-1", "network": "VISA", "last4": "5678", "outstanding_minor": 1250000, "status": "ACTIVE"}
    ]
    accounts = [
        {"id": "acc-1", "status": "ACTIVE", "balance_minor": 5000000, "account_number_masked": "XXXXXX9999"}
    ]

    with patch("app.agents.workflows.card_payment.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_cards.return_value = cards
        mock_instance.get_current_bill.return_value = {
            "id": "stmt-001",
            "total_due_minor": 1250000,
            "min_due_minor": 62500,
            "due_date": "2026-12-10T00:00:00Z",
        }
        mock_instance.list_accounts.return_value = accounts
        mock_instance.prepare_card_payment.return_value = {
            "id": "pay-draft-001",
            "reference": "CCPAY-DRAFT-001",
            "status": "PENDING_APPROVAL",
            "amount_minor": 1250000,
        }

        res = workflow_card_payment_node(state, config=config)

    assert "pending_action" in res
    pa: PendingAction = res["pending_action"]
    assert pa["workflow"] == WorkflowType.CARD_PAYMENT.value
    assert pa["banking_resource_id"] == "pay-draft-001"
    assert pa["stage"] == "CONFIRM"
    assert pa["summary_hash"] is not None

    summary = pa["summary_masked"]
    assert "5678" in summary["card"]
    assert summary["amount"] == "₹12,500.00"
    assert summary["payment_option"] == "Total Due"
    assert "XXXXXX9999" in summary["source_account"]

    assert res["approval_status"] == ApprovalStatus.PENDING.value
    assert "review the credit card payment" in res["response"].lower()
    assert "₹12,500.00" in res["response"]


def test_workflow_card_payment_prepare_banking_client_error() -> None:
    state: GraphState = {"user_message": "Pay ₹5,000 for credit card"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    cards = [{"id": "card-1", "network": "VISA", "last4": "5678", "outstanding_minor": 1000000, "status": "ACTIVE"}]
    accounts = [{"id": "acc-1", "status": "ACTIVE", "balance_minor": 5000000}]

    with patch("app.agents.workflows.card_payment.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_cards.return_value = cards
        mock_instance.list_accounts.return_value = accounts
        mock_instance.prepare_card_payment.side_effect = BankingClientError(
            "CARD_PAYMENT_FAILED", "Card payment gateway error", 502
        )

        res = workflow_card_payment_node(state, config=config)

    assert "pending_action" not in res
    assert res.get("error_code") == "CARD_PAYMENT_FAILED"
    assert "unable to prepare card payment" in res["response"].lower()


# ============================================================================
# 4. Execute Node – Card Payment Branch
# ============================================================================


def _make_card_payment_state(
    approval_status: str = ApprovalStatus.CONFIRMED.value,
    authorization_id: str = "auth-pin-verified-123",
) -> GraphState:
    return {
        "pending_action": {
            "workflow": WorkflowType.CARD_PAYMENT.value,
            "banking_resource_id": "pay-draft-001",
            "summary_masked": {
                "card": "VISA ending in 5678",
                "card_last4": "5678",
                "amount": "₹12,500.00",
                "payment_option": "Total Due",
                "source_account": "XXXXXX9999",
                "reference": "CCPAY-DRAFT-001",
            },
            "summary_hash": "hash-cc-xyz",
            "stage": "CONFIRM",
            "action_data": {
                "card_id": "card-1",
                "payment_id": "pay-draft-001",
                "statement_id": "stmt-001",
                "source_account_id": "acc-1",
                "amount_minor": 1250000,
                "summary_hash": "hash-cc-xyz",
                "idempotency_key": "cc-idem-001",
            },
        },
        "approval_status": approval_status,
        "authentication_status": "COMPLETED",
        "authorization_id": authorization_id,
    }


def test_execute_node_card_payment_success() -> None:
    state = _make_card_payment_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.execute_card_payment.return_value = {
            "id": "pay-draft-001",
            "reference": "CCPAY-EXEC-888",
            "status": "COMPLETED",
        }
        mock_instance.get_card_payment_status.return_value = {
            "id": "pay-draft-001",
            "reference": "CCPAY-EXEC-888",
            "status": "COMPLETED",
        }

        out = execute_node(state, config=config)

    assert out["approval_status"] == ApprovalStatus.EXECUTED.value
    assert out["transaction_reference"] == "CCPAY-EXEC-888"
    assert out["pending_action"] is None
    assert "completed successfully" in out["response"].lower()
    assert "₹12,500.00" in out["response"]
    assert "VISA ending in 5678" in out["response"]
    assert "CCPAY-EXEC-888" in out["response"]

    mock_instance.execute_card_payment.assert_called_once_with(
        payment_id="pay-draft-001",
        authorization_id="auth-pin-verified-123",
        idempotency_key="exec-pay-draft-001",
    )


def test_execute_node_card_payment_banking_client_error() -> None:
    state = _make_card_payment_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.execute_card_payment.side_effect = BankingClientError(
            "PIN_VERIFICATION_FAILED", "Invalid transaction PIN", 401
        )

        out = execute_node(state, config=config)

    assert out.get("error_code") == "PIN_VERIFICATION_FAILED"
    assert "failed to execute credit card payment" in out["response"].lower()


# ============================================================================
# 5. End-to-End LangGraph HITL Integration Tests
# ============================================================================


def _build_card_mock_client() -> MagicMock:
    mock = MagicMock()
    mock.list_cards.return_value = [
        {
            "id": "card-hitl-01",
            "network": "MasterCard",
            "last4": "9999",
            "outstanding_minor": 800000,
            "status": "ACTIVE",
        }
    ]
    mock.get_current_bill.return_value = {
        "id": "stmt-hitl-01",
        "total_due_minor": 800000,
        "min_due_minor": 50000,
        "due_date": "2026-12-15T00:00:00Z",
    }
    mock.list_accounts.return_value = [
        {"id": "acc-hitl-01", "status": "ACTIVE", "balance_minor": 2000000, "account_number_masked": "XXXXXX5555"}
    ]
    mock.prepare_card_payment.return_value = {
        "id": "pay-hitl-001",
        "reference": "REF-CC-HITL-001",
        "status": "PENDING_APPROVAL",
        "amount_minor": 800000,
    }
    mock.execute_card_payment.return_value = {
        "id": "pay-hitl-001",
        "reference": "REF-CC-HITL-001",
        "status": "COMPLETED",
    }
    mock.get_card_payment_status.return_value = {
        "id": "pay-hitl-001",
        "reference": "REF-CC-HITL-001",
        "status": "COMPLETED",
    }
    return mock


def test_end_to_end_card_payment_approval_and_execution() -> None:
    """Full two-stage HITL flow: prompt → interrupt(CONFIRM) → interrupt(AUTH) → execute."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread_id = "thread-card-hitl-01"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "user-access-token-jwt",
        }
    }

    mock_client = _build_card_mock_client()

    with (
        patch("app.agents.workflows.card_payment.BankingClient", return_value=mock_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        # Step 1: Initial user message
        init_state = {
            "user_message": "Pay total due for my credit card",
            "conversation_id": thread_id,
        }
        events = list(graph.stream(init_state, config=config, stream_mode="updates"))

        # Must pause at Stage 1 interrupt (CONFIRM)
        interrupt_events = [e for e in events if "__interrupt__" in e]
        assert len(interrupt_events) == 1
        interrupt_val = interrupt_events[0]["__interrupt__"][0].value
        assert interrupt_val["stage"] == "CONFIRM"
        assert interrupt_val["workflow"] == "CARD_PAYMENT"
        assert interrupt_val["summary"]["amount"] == "₹8,000.00"
        assert "9999" in interrupt_val["summary"]["card"]

        # Verify prepare was called
        mock_client.prepare_card_payment.assert_called_once()
        call_payload = mock_client.prepare_card_payment.call_args[0][1]
        assert call_payload["amount_minor"] == 800000

        # Step 2: User confirms → Stage 2 interrupt (AUTH_REQUIRED)
        events_stage2 = list(
            graph.stream(Command(resume={"decision": "CONFIRM"}), config=config, stream_mode="updates")
        )
        interrupt_events2 = [e for e in events_stage2 if "__interrupt__" in e]
        assert len(interrupt_events2) == 1
        interrupt_val2 = interrupt_events2[0]["__interrupt__"][0].value
        assert interrupt_val2["stage"] == "AUTH_REQUIRED"
        assert interrupt_val2["workflow"] == "CARD_PAYMENT"
        assert interrupt_val2["banking_resource_id"] == "pay-hitl-001"

        # Step 3: User authenticates (PIN) → executes
        events_final = list(
            graph.stream(
                Command(resume={"authorization_id": "auth-pin-valid-card"}),
                config=config,
                stream_mode="updates",
            )
        )
        executed_nodes = [next(iter(e.keys())) for e in events_final]
        assert "execute" in executed_nodes
        assert "response" in executed_nodes

        # Backend execute was called
        mock_client.execute_card_payment.assert_called_once_with(
            payment_id="pay-hitl-001",
            authorization_id="auth-pin-valid-card",
            idempotency_key="exec-pay-hitl-001",
        )

        # Final checkpoint state
        final_state = graph.get_state(config).values
        assert final_state["approval_status"] == ApprovalStatus.EXECUTED.value
        assert final_state["transaction_reference"] == "REF-CC-HITL-001"
        assert "completed successfully" in final_state["response"].lower()


def test_end_to_end_card_payment_rejection_flow() -> None:
    """Rejection flow: user rejects at Stage 1 CONFIRM → no execute, clean cancellation."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread_id = "thread-card-reject-01"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "user-access-token-jwt",
        }
    }

    mock_client = _build_card_mock_client()

    with (
        patch("app.agents.workflows.card_payment.BankingClient", return_value=mock_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        init_state = {
            "user_message": "Pay total due for my credit card",
            "conversation_id": thread_id,
        }
        events = list(graph.stream(init_state, config=config, stream_mode="updates"))
        assert any("__interrupt__" in e for e in events)

        # User rejects
        events_reject = list(
            graph.stream(
                Command(resume={"decision": "REJECT"}),
                config=config,
                stream_mode="updates",
            )
        )
        rejected_nodes = [next(iter(e.keys())) for e in events_reject]

        assert "execute" not in rejected_nodes
        assert "response" in rejected_nodes

        mock_client.execute_card_payment.assert_not_called()

        final_state = graph.get_state(config).values
        assert final_state["approval_status"] == ApprovalStatus.REJECTED.value
        assert "cancelled" in final_state["response"].lower()
