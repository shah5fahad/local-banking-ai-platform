"""Comprehensive unit and integration tests for Phase 5 task T5.3: Transfer workflow.

Covers:
- Amount parsing: various INR formats (₹, Rs, commas, paise)
- Field extraction: amount, beneficiary name, channel, remark from text + history
- Missing field prompts (no amount, no beneficiary, both missing)
- Beneficiary lookup: not found, multiple matches (disambiguation), exact match
- Balance check: insufficient funds
- Limits check: per-transaction and daily remaining
- Successful draft: PendingAction with masked summary and correct summary_hash
- BankingClientError during prepare_transfer
- Execute node transfer branch: success path (mocked BankingClient)
- Execute node transfer branch: BankingClientError and generic exception handling
- End-to-end LangGraph HITL: prompt → interrupt(CONFIRM) → interrupt(AUTH) → execute
- Rejection flow: prompt → interrupt(CONFIRM) → REJECT → cancel_transfer called, no execute
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.nodes.execute import execute_node
from app.agents.state import GraphState, PendingAction
from app.agents.workflows.transfer import (
    extract_transfer_fields,
    format_inr,
    parse_amount_to_minor,
    workflow_transfer_node,
)
from app.integrations.banking_client import BankingClientError
from app.models.approval import ApprovalStatus, WorkflowType

# ============================================================================
# 1. Amount Parsing Unit Tests
# ============================================================================


def test_parse_amount_to_minor_rupee_symbol() -> None:
    assert parse_amount_to_minor("₹5,000") == 500000


def test_parse_amount_to_minor_plain_number() -> None:
    assert parse_amount_to_minor("5000") == 500000


def test_parse_amount_to_minor_decimal() -> None:
    assert parse_amount_to_minor("Rs 5000.50") == 500050


def test_parse_amount_to_minor_lakh_format() -> None:
    assert parse_amount_to_minor("₹1,00,000") == 10000000


def test_parse_amount_to_minor_inr_prefix() -> None:
    assert parse_amount_to_minor("INR 2500") == 250000


def test_parse_amount_to_minor_no_amount_returns_none() -> None:
    assert parse_amount_to_minor("transfer funds to my friend") is None


def test_parse_amount_to_minor_zero_returns_none() -> None:
    assert parse_amount_to_minor("₹0") is None


def test_format_inr() -> None:
    assert format_inr(500000) == "₹5,000.00"
    assert format_inr(100) == "₹1.00"
    assert format_inr(10000000) == "₹1,00,000.00"


# ============================================================================
# 2. Field Extraction Unit Tests
# ============================================================================


def test_extract_fields_full_one_shot() -> None:
    text = "Transfer ₹5,000 to Rahul Sharma via NEFT for rent"
    res = extract_transfer_fields(text)
    assert res["amount_minor"] == 500000
    assert res["beneficiary_name"] is not None
    assert "Rahul" in res["beneficiary_name"]
    assert res["channel"] == "NEFT"
    assert res["remark"] is not None


def test_extract_fields_imps_default() -> None:
    text = "Send ₹2,000 to Priya"
    res = extract_transfer_fields(text)
    assert res["channel"] == "IMPS"


def test_extract_fields_rtgs_channel() -> None:
    text = "Transfer 50000 to Sharma via RTGS"
    res = extract_transfer_fields(text)
    assert res["channel"] == "RTGS"


def test_extract_fields_conversational_history_amount() -> None:
    history = [
        HumanMessage(content="I want to send money to Rahul"),
        AIMessage(content="How much would you like to send to Rahul?"),
    ]
    curr = "Transfer ₹3,000"
    res = extract_transfer_fields(curr, history)
    assert res["amount_minor"] == 300000
    # Beneficiary name from history
    assert res["beneficiary_name"] is not None


def test_extract_fields_conversational_history_bene_name() -> None:
    history = [
        HumanMessage(content="Please transfer ₹10,000 to Neha Gupta"),
    ]
    # Current message has no beneficiary, should pick from history
    curr = "Yes, go ahead"
    res = extract_transfer_fields(curr, history)
    # Amount from history
    assert res["amount_minor"] == 1000000


# ============================================================================
# 3. Missing Field Prompts
# ============================================================================


def test_workflow_transfer_missing_all_fields() -> None:
    state: GraphState = {"user_message": "I want to transfer some money"}
    res = workflow_transfer_node(state, config={})
    assert "pending_action" not in res
    assert "recipient" in res["response"].lower() or "amount" in res["response"].lower()
    assert res["approval_status"] == "NONE"


def test_workflow_transfer_missing_beneficiary() -> None:
    state: GraphState = {"user_message": "Transfer ₹5,000"}
    res = workflow_transfer_node(state, config={})
    assert "pending_action" not in res
    assert "who" in res["response"].lower() or "transfer" in res["response"].lower()


def test_workflow_transfer_missing_amount() -> None:
    state: GraphState = {
        "user_message": "Transfer to Rahul Sharma",
        "messages": [],
    }
    res = workflow_transfer_node(state, config={})
    assert "pending_action" not in res
    assert "how much" in res["response"].lower() or "rahul" in res["response"].lower()


def test_workflow_transfer_no_access_token() -> None:
    state: GraphState = {"user_message": "Transfer ₹2,000 to Rahul"}
    res = workflow_transfer_node(state, config={"configurable": {}})
    assert "pending_action" not in res
    assert "log in" in res["response"].lower() or "authentication" in res["response"].lower()
    assert res.get("error_code") == "UNAUTHENTICATED"


# ============================================================================
# 4. Beneficiary Lookup Tests
# ============================================================================


def test_workflow_transfer_beneficiary_not_found() -> None:
    state: GraphState = {
        "user_message": "Transfer ₹5,000 to Rahul Sharma",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = []

        res = workflow_transfer_node(state, config=config)
        assert "pending_action" not in res
        assert "Rahul Sharma" in res["response"]
        assert "couldn't find" in res["response"].lower() or "not find" in res["response"].lower()
        assert res["approval_status"] == "NONE"


def test_workflow_transfer_multiple_beneficiaries_disambiguation() -> None:
    state: GraphState = {
        "user_message": "Transfer ₹5,000 to Rahul",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    benes = [
        {"id": "b1", "name": "Rahul Sharma", "last4": "1234", "bank_name": "HDFC Bank",
         "account_number_masked": "XXXXXX1234"},
        {"id": "b2", "name": "Rahul Verma", "last4": "5678", "bank_name": "ICICI Bank",
         "account_number_masked": "XXXXXX5678"},
    ]

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = benes

        res = workflow_transfer_node(state, config=config)
        assert "pending_action" not in res
        # Both names should appear in disambiguation list
        assert "Rahul Sharma" in res["response"]
        assert "Rahul Verma" in res["response"]
        assert res["approval_status"] == "NONE"


def test_workflow_transfer_single_beneficiary_exact_match() -> None:
    """When exactly one beneficiary is found, proceed to draft without disambiguation."""
    state: GraphState = {
        "user_message": "Transfer ₹5,000 to Priya Patel",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    bene = {
        "id": "b-priya-01",
        "name": "Priya Patel",
        "last4": "9876",
        "bank_name": "SBI",
        "account_number_masked": "XXXXXX9876",
        "nickname": None,
    }

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = [bene]
        mock_instance.list_accounts.return_value = [
            {"id": "acc-1", "status": "ACTIVE", "balance_minor": 1000000}
        ]
        mock_instance.get_transfer_limits.return_value = {
            "per_transaction_limit_minor": 10000000,
            "daily_remaining_minor": 5000000,
        }
        mock_instance.prepare_transfer.return_value = {
            "id": "txn-draft-001",
            "summary_hash": "hash-abc-123",
            "fee_minor": 500,
            "total_debit_minor": 500500,
            "reference": "REF-TEST-001",
        }

        res = workflow_transfer_node(state, config=config)

        assert "pending_action" in res
        pa: PendingAction = res["pending_action"]
        assert pa["workflow"] == WorkflowType.TRANSFER.value
        assert pa["banking_resource_id"] == "txn-draft-001"
        assert pa["summary_hash"] == "hash-abc-123"
        assert pa["stage"] == "CONFIRM"
        assert pa["summary_masked"]["beneficiary"] == "Priya Patel"
        assert pa["summary_masked"]["account_masked"] == "XXXXXX9876"
        assert pa["summary_masked"]["amount"] == "₹5,000.00"
        assert res["approval_status"] == ApprovalStatus.PENDING.value
        assert "Priya Patel" in res["response"]


# ============================================================================
# 5. Balance & Limits Tests
# ============================================================================


def test_workflow_transfer_insufficient_balance() -> None:
    state: GraphState = {
        "user_message": "Transfer ₹50,000 to Rahul Sharma",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = [
            {"id": "b-rahul", "name": "Rahul Sharma", "last4": "1234",
             "account_number_masked": "XXXXXX1234", "bank_name": "HDFC", "nickname": None}
        ]
        mock_instance.list_accounts.return_value = [
            {"id": "acc-1", "status": "ACTIVE", "balance_minor": 100000}  # only ₹1,000
        ]

        res = workflow_transfer_node(state, config=config)
        assert "pending_action" not in res
        assert "insufficient" in res["response"].lower() or "balance" in res["response"].lower()
        assert res["approval_status"] == "NONE"


def test_workflow_transfer_per_transaction_limit_exceeded() -> None:
    state: GraphState = {
        "user_message": "Transfer ₹2,00,000 to Rahul Sharma",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = [
            {"id": "b-r", "name": "Rahul Sharma", "last4": "1234",
             "account_number_masked": "XXXXXX1234", "bank_name": "HDFC", "nickname": None}
        ]
        mock_instance.list_accounts.return_value = [
            {"id": "acc-1", "status": "ACTIVE", "balance_minor": 50000000}  # ₹5,00,000
        ]
        mock_instance.get_transfer_limits.return_value = {
            "per_transaction_limit_minor": 10000000,  # ₹1,00,000
            "daily_remaining_minor": 50000000,
        }

        res = workflow_transfer_node(state, config=config)
        assert "pending_action" not in res
        assert "per-transaction" in res["response"].lower() or "limit" in res["response"].lower()


def test_workflow_transfer_daily_limit_exceeded() -> None:
    state: GraphState = {
        "user_message": "Transfer ₹5,000 to Rahul Sharma",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = [
            {"id": "b-r", "name": "Rahul Sharma", "last4": "1234",
             "account_number_masked": "XXXXXX1234", "bank_name": "HDFC", "nickname": None}
        ]
        mock_instance.list_accounts.return_value = [
            {"id": "acc-1", "status": "ACTIVE", "balance_minor": 1000000}
        ]
        mock_instance.get_transfer_limits.return_value = {
            "per_transaction_limit_minor": 10000000,
            "daily_remaining_minor": 100,  # Only ₹1 remaining daily
        }

        res = workflow_transfer_node(state, config=config)
        assert "pending_action" not in res
        assert "daily" in res["response"].lower() or "limit" in res["response"].lower()


def test_workflow_transfer_no_active_accounts() -> None:
    state: GraphState = {
        "user_message": "Transfer ₹5,000 to Rahul Sharma",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = [
            {"id": "b-r", "name": "Rahul Sharma", "last4": "1234",
             "account_number_masked": "XXXXXX1234", "bank_name": "HDFC", "nickname": None}
        ]
        mock_instance.list_accounts.return_value = [
            {"id": "acc-1", "status": "CLOSED", "balance_minor": 1000000}
        ]

        res = workflow_transfer_node(state, config=config)
        assert "pending_action" not in res
        assert "active" in res["response"].lower() or "account" in res["response"].lower()


# ============================================================================
# 6. Draft Creation Error Handling
# ============================================================================


def test_workflow_transfer_prepare_banking_client_error() -> None:
    state: GraphState = {
        "user_message": "Transfer ₹5,000 to Priya Patel",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = [
            {"id": "b-p", "name": "Priya Patel", "last4": "9876",
             "account_number_masked": "XXXXXX9876", "bank_name": "SBI", "nickname": None}
        ]
        mock_instance.list_accounts.return_value = [
            {"id": "acc-1", "status": "ACTIVE", "balance_minor": 1000000}
        ]
        mock_instance.get_transfer_limits.return_value = {
            "per_transaction_limit_minor": 10000000,
            "daily_remaining_minor": 5000000,
        }
        mock_instance.prepare_transfer.side_effect = BankingClientError(
            "TRANSFER_LIMIT_EXCEEDED", "Daily limit reached", 422
        )

        res = workflow_transfer_node(state, config=config)
        assert "pending_action" not in res
        assert "unable to prepare" in res["response"].lower()
        assert res.get("error_code") == "TRANSFER_LIMIT_EXCEEDED"


def test_workflow_transfer_prepare_generic_exception() -> None:
    state: GraphState = {
        "user_message": "Transfer ₹5,000 to Priya Patel",
    }
    config = {"configurable": {"access_token": "mock-token"}}

    with patch("app.agents.workflows.transfer.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = [
            {"id": "b-p", "name": "Priya Patel", "last4": "9876",
             "account_number_masked": "XXXXXX9876", "bank_name": "SBI", "nickname": None}
        ]
        mock_instance.list_accounts.return_value = [
            {"id": "acc-1", "status": "ACTIVE", "balance_minor": 1000000}
        ]
        mock_instance.get_transfer_limits.return_value = {
            "per_transaction_limit_minor": 10000000,
            "daily_remaining_minor": 5000000,
        }
        mock_instance.prepare_transfer.side_effect = ConnectionError("Service unreachable")

        res = workflow_transfer_node(state, config=config)
        assert "pending_action" not in res
        assert "unable to prepare" in res["response"].lower()
        assert res.get("error_code") == "PREPARE_FAILED"


# ============================================================================
# 7. Execute Node – Transfer Branch Tests
# ============================================================================


def _make_transfer_state(
    approval_status: str = ApprovalStatus.CONFIRMED.value,
    authorization_id: str = "auth-token-valid",
) -> GraphState:
    return {
        "pending_action": {
            "workflow": WorkflowType.TRANSFER.value,
            "banking_resource_id": "txn-exec-001",
            "summary_masked": {
                "beneficiary": "Priya Patel",
                "account_masked": "XXXXXX9876",
                "amount": "₹5,000.00",
                "charges": "₹5.00",
                "total_debit": "₹5,005.00",
                "reference": "REF-DRAFT-001",
            },
            "summary_hash": "summary-hash-xyz",
            "stage": "CONFIRM",
            "action_data": {
                "txn_id": "txn-exec-001",
                "summary_hash": "summary-hash-xyz",
                "idempotency_key": "idem-key-123",
            },
        },
        "approval_status": approval_status,
        "authentication_status": "COMPLETED",
        "authorization_id": authorization_id,
    }


def test_execute_node_transfer_success() -> None:
    state = _make_transfer_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.execute_transfer.return_value = {
            "id": "txn-exec-001",
            "status": "PROCESSING",
            "reference": "REF-EXEC-999",
        }
        mock_instance.get_transfer_status.return_value = {
            "id": "txn-exec-001",
            "status": "COMPLETED",
            "reference": "REF-EXEC-999",
        }

        out = execute_node(state, config=config)

    assert out["approval_status"] == ApprovalStatus.EXECUTED.value
    assert out["transaction_reference"] == "REF-EXEC-999"
    assert out["pending_action"] is None
    assert "Priya Patel" in out["response"]
    assert "₹5,000.00" in out["response"]
    assert "REF-EXEC-999" in out["response"]
    assert "COMPLETED" in out["response"]

    mock_instance.execute_transfer.assert_called_once_with(
        txn_id="txn-exec-001",
        authorization_id="auth-token-valid",
        summary_hash="summary-hash-xyz",
        idempotency_key="exec-txn-exec-001",
    )
    mock_instance.get_transfer_status.assert_called_once_with("txn-exec-001")


def test_execute_node_transfer_banking_client_error() -> None:
    state = _make_transfer_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.execute_transfer.side_effect = BankingClientError(
            "AUTHORIZATION_EXPIRED", "Authorization token expired", 401
        )

        out = execute_node(state, config=config)

    assert "error_code" in out
    assert out["error_code"] == "AUTHORIZATION_EXPIRED"
    assert "failed to execute transfer" in out["response"].lower()


def test_execute_node_transfer_generic_exception() -> None:
    state = _make_transfer_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.execute_transfer.side_effect = RuntimeError("Unexpected crash")

        out = execute_node(state, config=config)

    assert out.get("error_code") == "EXECUTION_FAILED"
    assert "failed to execute transfer" in out["response"].lower()


def test_execute_node_no_pending_action_returns_empty() -> None:
    state: GraphState = {"approval_status": ApprovalStatus.CONFIRMED.value}
    out = execute_node(state, config={})
    assert out == {}


def test_execute_node_rejected_status_returns_empty() -> None:
    state = _make_transfer_state(approval_status=ApprovalStatus.REJECTED.value)
    out = execute_node(state, config={})
    assert out == {}


# ============================================================================
# 8. End-to-End LangGraph HITL Integration Tests
# ============================================================================


def _build_transfer_mock_client(*, cancel_called: bool = False) -> MagicMock:
    """Build a fully-configured mock BankingClient for transfer e2e tests."""
    mock = MagicMock()
    mock.list_beneficiaries.return_value = [
        {
            "id": "b-rahul-01",
            "name": "Rahul Sharma",
            "last4": "4321",
            "bank_name": "HDFC Bank",
            "account_number_masked": "XXXXXX4321",
            "nickname": None,
        }
    ]
    mock.list_accounts.return_value = [
        {"id": "acc-savings-01", "status": "ACTIVE", "balance_minor": 2000000}
    ]
    mock.get_transfer_limits.return_value = {
        "per_transaction_limit_minor": 10000000,
        "daily_remaining_minor": 5000000,
    }
    mock.prepare_transfer.return_value = {
        "id": "txn-hitl-001",
        "summary_hash": "hash-hitl-sha256",
        "fee_minor": 1000,
        "total_debit_minor": 501000,
        "reference": "REF-HITL-001",
    }
    mock.execute_transfer.return_value = {
        "id": "txn-hitl-001",
        "status": "PROCESSING",
        "reference": "REF-HITL-001",
    }
    mock.get_transfer_status.return_value = {
        "id": "txn-hitl-001",
        "status": "COMPLETED",
        "reference": "REF-HITL-001",
    }
    return mock


def test_end_to_end_transfer_approval_and_execution() -> None:
    """Full HITL flow: prompt → Stage1(CONFIRM) → Stage2(AUTH) → execute → status."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread_id = "thread-transfer-hitl-01"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "user-access-token-jwt",
        }
    }

    mock_client = _build_transfer_mock_client()

    with (
        patch("app.agents.workflows.transfer.BankingClient", return_value=mock_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        # --- Step 1: Initial user message ---
        init_state = {
            "user_message": "Transfer ₹5,000 to Rahul Sharma",
            "conversation_id": thread_id,
        }
        events = list(graph.stream(init_state, config=config, stream_mode="updates"))

        # Graph must pause at Stage 1 interrupt (CONFIRM)
        interrupt_events = [e for e in events if "__interrupt__" in e]
        assert len(interrupt_events) == 1
        interrupt_val = interrupt_events[0]["__interrupt__"][0].value
        assert interrupt_val["stage"] == "CONFIRM"
        assert interrupt_val["workflow"] == "TRANSFER"
        assert interrupt_val["summary"]["beneficiary"] == "Rahul Sharma"
        assert interrupt_val["summary"]["account_masked"] == "XXXXXX4321"
        assert interrupt_val["summary"]["amount"] == "₹5,000.00"

        # Verify prepare_transfer was called
        mock_client.prepare_transfer.assert_called_once()
        call_data = mock_client.prepare_transfer.call_args[0][0]
        assert call_data["beneficiary_id"] == "b-rahul-01"
        assert call_data["amount_minor"] == 500000

        # --- Step 2: User confirms → Stage 2 interrupt (AUTH_REQUIRED) ---
        events_stage2 = list(
            graph.stream(Command(resume={"decision": "CONFIRM"}), config=config, stream_mode="updates")
        )
        interrupt_events2 = [e for e in events_stage2 if "__interrupt__" in e]
        assert len(interrupt_events2) == 1
        interrupt_val2 = interrupt_events2[0]["__interrupt__"][0].value
        assert interrupt_val2["stage"] == "AUTH_REQUIRED"
        assert interrupt_val2["workflow"] == "TRANSFER"
        assert interrupt_val2["banking_resource_id"] == "txn-hitl-001"

        # cancel_transfer NOT called on CONFIRM
        mock_client.cancel_transfer.assert_not_called()

        # --- Step 3: User authenticates → execute ---
        events_final = list(
            graph.stream(
                Command(resume={"authorization_id": "auth-pin-verified-token"}),
                config=config,
                stream_mode="updates",
            )
        )
        executed_nodes = [next(iter(e.keys())) for e in events_final]
        assert "execute" in executed_nodes
        assert "response" in executed_nodes

        # Backend write assertions
        mock_client.execute_transfer.assert_called_once_with(
            txn_id="txn-hitl-001",
            authorization_id="auth-pin-verified-token",
            summary_hash="hash-hitl-sha256",
            idempotency_key="exec-txn-hitl-001",
        )
        mock_client.get_transfer_status.assert_called_once_with("txn-hitl-001")

        # Final checkpoint state
        final_state = graph.get_state(config).values
        assert final_state["approval_status"] == ApprovalStatus.EXECUTED.value
        assert final_state["transaction_reference"] == "REF-HITL-001"
        assert "Rahul Sharma" in final_state["response"]
        assert "COMPLETED" in final_state["response"]


def test_end_to_end_transfer_rejection_cancels_draft() -> None:
    """Rejection flow: user rejects at CONFIRM → cancel_transfer called, execute skipped."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread_id = "thread-transfer-reject-01"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "user-access-token-jwt",
        }
    }

    mock_client = _build_transfer_mock_client()

    with (
        patch("app.agents.workflows.transfer.BankingClient", return_value=mock_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        # Step 1: prompt
        init_state = {
            "user_message": "Transfer ₹5,000 to Rahul Sharma",
            "conversation_id": thread_id,
        }
        events = list(graph.stream(init_state, config=config, stream_mode="updates"))
        assert any("__interrupt__" in e for e in events)

        # Verify draft was created
        mock_client.prepare_transfer.assert_called_once()

        # Step 2: User clicks REJECT
        events_reject = list(
            graph.stream(
                Command(resume={"decision": "REJECT"}),
                config=config,
                stream_mode="updates",
            )
        )
        rejected_nodes = [next(iter(e.keys())) for e in events_reject]

        # execute node must NOT be reached
        assert "execute" not in rejected_nodes
        assert "response" in rejected_nodes

        # cancel_transfer must be called on the banking draft
        mock_client.cancel_transfer.assert_called_once_with("txn-hitl-001")

        # execute_transfer must NOT be called
        mock_client.execute_transfer.assert_not_called()

        # Final checkpoint state
        final_state = graph.get_state(config).values
        assert final_state["approval_status"] == ApprovalStatus.REJECTED.value
        assert "cancelled" in final_state["response"].lower()
