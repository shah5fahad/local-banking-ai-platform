"""Comprehensive unit and integration tests for Phase 5 task T5.2: Beneficiary workflow.

Covers:
- Field extraction (one-shot, conversational, IFSC bank name inference)
- Missing field prompts and guidance
- Format validation (account number 9-18 digits, IFSC format)
- Duplicate beneficiary detection via BankingClient
- Challenge creation and canonical payload_hash computation
- Preparation of PendingAction with masked review details
- Execution node: calling create_beneficiary with approval token
- End-to-end LangGraph HITL execution:
    collect -> draft -> approval_gate (interrupt 1: confirm) ->
    confirm -> approval_gate (interrupt 2: auth_required) ->
    resume with authorization_id -> execute -> response
- Rejection flow: confirm -> reject -> cancellation without backend write
"""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.nodes.execute import execute_node
from app.agents.state import GraphState, PendingAction
from app.agents.workflows.beneficiary import (
    extract_beneficiary_fields,
    workflow_beneficiary_node,
)
from app.integrations.banking_client import BankingClientError
from app.models.approval import ApprovalStatus, WorkflowType

# ============================================================================
# 1. Field Extraction & Validation Unit Tests
# ============================================================================


def test_extract_beneficiary_fields_one_shot() -> None:
    text = (
        "Add beneficiary Rahul Sharma, account number 987654321098, "
        "IFSC ICIC0000456, bank ICICI Bank, nickname Rahul"
    )
    res = extract_beneficiary_fields(text)
    assert res["name"] == "Rahul Sharma"
    assert res["account_number"] == "987654321098"
    assert res["ifsc"] == "ICIC0000456"
    assert res["bank_name"] == "ICICI Bank"
    assert res["nickname"] == "Rahul"


def test_extract_beneficiary_fields_conversational_history() -> None:
    history = [
        HumanMessage(content="I want to add a beneficiary for Alice Smith"),
        AIMessage(content="Please provide the account number and IFSC code for Alice Smith."),
    ]
    curr_msg = "Account is 123456789012, IFSC is HDFC0001234"
    res = extract_beneficiary_fields(curr_msg, history)
    assert res["name"] == "Alice Smith"
    assert res["account_number"] == "123456789012"
    assert res["ifsc"] == "HDFC0001234"
    # Bank name inferred from HDFC prefix
    assert res["bank_name"] == "HDFC Bank"


def test_workflow_beneficiary_missing_fields_prompt() -> None:
    # 1. All missing
    state_all_missing: GraphState = {"user_message": "Add a new beneficiary"}
    res1 = workflow_beneficiary_node(state_all_missing, config={})
    assert "pending_action" not in res1
    assert "full name, account number, IFSC code, and bank name" in res1["response"]

    # 2. Only name provided
    state_name_only: GraphState = {"user_message": "Add beneficiary Robert"}
    res2 = workflow_beneficiary_node(state_name_only, config={})
    assert "pending_action" not in res2
    assert "account number" in res2["response"].lower()
    assert "ifsc" in res2["response"].lower()


def test_workflow_beneficiary_format_validation() -> None:
    # 1. Invalid account number (too short: 4 digits)
    state_bad_acc: GraphState = {
        "user_message": (
            "Add beneficiary Bob, account 1234, IFSC HDFC0001234, bank HDFC Bank"
        )
    }
    res_acc = workflow_beneficiary_node(state_bad_acc, config={})
    assert "pending_action" not in res_acc
    assert "between 9 and 18 numeric digits" in res_acc["response"]

    # 2. Invalid IFSC pattern
    state_bad_ifsc: GraphState = {
        "user_message": (
            "Add beneficiary Bob, account 123456789012, IFSC INVALID123, bank HDFC Bank"
        )
    }
    res_ifsc = workflow_beneficiary_node(state_bad_ifsc, config={})
    assert "pending_action" not in res_ifsc
    assert "invalid" in res_ifsc["response"].lower()
    assert "HDFC0001234" in res_ifsc["response"]


def test_workflow_beneficiary_duplicate_detection() -> None:
    state: GraphState = {
        "user_message": (
            "Add beneficiary Priya Singh, account 987654321098, "
            "IFSC SBIN0001234, bank State Bank of India"
        )
    }
    config = {"configurable": {"access_token": "mock-token-xyz"}}

    existing_mock = [
        {
            "id": "bene-existing-1",
            "name": "Priya Singh",
            "last4": "1098",
            "ifsc": "SBIN0001234",
            "status": "ACTIVE",
        }
    ]

    with patch("app.agents.workflows.beneficiary.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = existing_mock

        res = workflow_beneficiary_node(state, config=config)
        assert "pending_action" not in res
        assert "already registered" in res["response"].lower()
        assert "Priya Singh" in res["response"]


def test_workflow_beneficiary_draft_and_challenge_creation() -> None:
    state: GraphState = {
        "user_message": (
            "Add beneficiary Vikram Verma, account 987654321098, "
            "IFSC ICIC0000456, bank ICICI Bank, nickname Vik"
        )
    }
    config = {"configurable": {"access_token": "mock-token-xyz"}}

    with patch("app.agents.workflows.beneficiary.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_beneficiaries.return_value = []
        mock_instance.create_approval_challenge.return_value = {
            "challenge_id": "ch-test-12345",
            "action": "BENEFICIARY_CREATE",
        }

        res = workflow_beneficiary_node(state, config=config)

        assert "pending_action" in res
        pa: PendingAction = res["pending_action"]
        assert pa["workflow"] == WorkflowType.BENEFICIARY.value
        assert pa["banking_resource_id"] == "ch-test-12345"
        assert pa["stage"] == "CONFIRM"
        assert pa["summary_masked"]["beneficiary_name"] == "Vikram Verma"
        assert pa["summary_masked"]["account_masked"] == "XXXXXX1098"
        assert pa["summary_masked"]["ifsc"] == "ICIC0000456"
        assert pa["summary_masked"]["bank_name"] == "ICICI Bank"

        # Verify canonical payload_hash
        expected_norm = "Vikram Verma|Vik|987654321098|ICIC0000456|ICICI Bank"
        expected_hash = hashlib.sha256(expected_norm.encode("utf-8")).hexdigest()
        assert pa["summary_hash"] == expected_hash

        # Verify challenge was requested on Banking API
        mock_instance.create_approval_challenge.assert_called_once_with(
            "BENEFICIARY_CREATE", expected_hash
        )


# ============================================================================
# 2. Execution Node Unit Tests
# ============================================================================


def test_execute_node_beneficiary_success() -> None:
    state: GraphState = {
        "pending_action": {
            "workflow": WorkflowType.BENEFICIARY.value,
            "banking_resource_id": "ch-123",
            "summary_masked": {
                "beneficiary_name": "Vikram Verma",
                "account_masked": "XXXXXX1098",
            },
            "summary_hash": "dummy-hash",
            "stage": "CONFIRM",
            "action_data": {
                "name": "Vikram Verma",
                "nickname": "Vik",
                "account_number": "987654321098",
                "ifsc": "ICIC0000456",
                "bank_name": "ICICI Bank",
            },
        },
        "approval_status": ApprovalStatus.CONFIRMED.value,
        "authentication_status": "COMPLETED",
        "authorization_id": "token-single-use-mfa",
    }
    config = {"configurable": {"access_token": "user-jwt-bearer"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.create_beneficiary.return_value = {
            "id": "bene-created-uuid",
            "name": "Vikram Verma",
            "last4": "1098",
            "status": "ACTIVE",
        }

        out = execute_node(state, config=config)

        assert out["approval_status"] == ApprovalStatus.EXECUTED.value
        assert out["transaction_reference"] == "bene-created-uuid"
        assert out["pending_action"] is None
        assert "Vikram Verma" in out["response"]
        assert "1098" in out["response"]

        mock_instance.create_beneficiary.assert_called_once_with(
            state["pending_action"]["action_data"],
            approval_token="token-single-use-mfa",  # noqa: S106
        )


def test_execute_node_beneficiary_failure_handled() -> None:
    state: GraphState = {
        "pending_action": {
            "workflow": WorkflowType.BENEFICIARY.value,
            "banking_resource_id": "ch-123",
            "summary_masked": {},
            "summary_hash": "hash",
            "action_data": {"name": "Bob"},
        },
        "approval_status": ApprovalStatus.CONFIRMED.value,
        "authentication_status": "COMPLETED",
        "authorization_id": "bad-token",
    }
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.create_beneficiary.side_effect = BankingClientError(
            "AUTHORIZATION_INVALID", "Invalid or expired approval token", 401
        )

        out = execute_node(state, config=config)
        assert out["error_code"] == "AUTHORIZATION_INVALID"
        assert "Failed to add beneficiary" in out["response"]


# ============================================================================
# 3. End-to-End LangGraph HITL Integration Tests
# ============================================================================


def test_end_to_end_beneficiary_approval_and_execution_graph() -> None:
    """Full workflow: user prompt -> interrupt(CONFIRM) -> interrupt(AUTH) -> execute."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)

    thread_id = "thread-bene-hitl-test"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "user-access-token-jwt",
        }
    }

    # Mock BankingClient so challenge and creation succeed
    mock_banking_client = MagicMock()
    mock_banking_client.list_beneficiaries.return_value = []
    mock_banking_client.create_approval_challenge.return_value = {
        "challenge_id": "ch-full-test-999",
        "action": "BENEFICIARY_CREATE",
    }
    mock_banking_client.create_beneficiary.return_value = {
        "id": "bene-uuid-777",
        "name": "Neha Sharma",
        "last4": "4321",
        "status": "ACTIVE",
    }

    with (
        patch("app.agents.workflows.beneficiary.BankingClient", return_value=mock_banking_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_banking_client),
    ):
        # Step 1: Initial invocation with user prompt
        init_state = {
            "user_message": (
                "Add beneficiary Neha Sharma, account 123456784321, "
                "IFSC HDFC0001234, bank HDFC Bank, nickname Neha"
            ),
            "conversation_id": thread_id,
        }

        events = list(graph.stream(init_state, config=config, stream_mode="updates"))

        # Check graph paused at interrupt Stage 1 (CONFIRM)
        interrupt_events = [e for e in events if "__interrupt__" in e]
        assert len(interrupt_events) == 1
        interrupt_val = interrupt_events[0]["__interrupt__"][0].value
        assert interrupt_val["stage"] == "CONFIRM"
        assert interrupt_val["workflow"] == "BENEFICIARY"
        assert interrupt_val["summary"]["beneficiary_name"] == "Neha Sharma"
        assert interrupt_val["summary"]["account_masked"] == "XXXXXX4321"

        # Step 2: User clicks CONFIRM -> resumes graph to Stage 2 (AUTH_REQUIRED)
        resume_confirm = Command(resume={"decision": "CONFIRM"})
        events_stage2 = list(graph.stream(resume_confirm, config=config, stream_mode="updates"))

        interrupt_events2 = [e for e in events_stage2 if "__interrupt__" in e]
        assert len(interrupt_events2) == 1
        interrupt_val2 = interrupt_events2[0]["__interrupt__"][0].value
        assert interrupt_val2["stage"] == "AUTH_REQUIRED"
        assert interrupt_val2["workflow"] == "BENEFICIARY"
        assert interrupt_val2["banking_resource_id"] == "ch-full-test-999"

        # Step 3: User authenticates with PIN directly at Banking API and passes approval token
        resume_auth = Command(resume={"authorization_id": "approval-tok-mfa-valid"})
        events_final = list(graph.stream(resume_auth, config=config, stream_mode="updates"))

        # Verify execution and final response
        executed_nodes = [next(iter(e.keys())) for e in events_final]
        assert "execute" in executed_nodes
        assert "response" in executed_nodes

        # Backend write was called with the approval token
        mock_banking_client.create_beneficiary.assert_called_once()
        call_args = mock_banking_client.create_beneficiary.call_args
        assert call_args.kwargs["approval_token"] == "approval-tok-mfa-valid"  # noqa: S105
        assert call_args.args[0]["name"] == "Neha Sharma"
        assert call_args.args[0]["account_number"] == "123456784321"

        # Check final checkpoint state
        state_final = graph.get_state(config).values
        assert state_final["approval_status"] == ApprovalStatus.EXECUTED.value
        assert state_final["transaction_reference"] == "bene-uuid-777"
        assert "Neha Sharma" in state_final["response"]
        assert "4321" in state_final["response"]


def test_end_to_end_beneficiary_rejection_graph() -> None:
    """Rejection workflow: user rejects at confirmation -> no backend write, clean cancellation."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)

    thread_id = "thread-bene-reject-test"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "user-access-token-jwt",
        }
    }

    mock_banking_client = MagicMock()
    mock_banking_client.list_beneficiaries.return_value = []
    mock_banking_client.create_approval_challenge.return_value = {
        "challenge_id": "ch-reject-123",
        "action": "BENEFICIARY_CREATE",
    }

    with (
        patch("app.agents.workflows.beneficiary.BankingClient", return_value=mock_banking_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_banking_client),
    ):
        # Step 1: User prompt
        init_state = {
            "user_message": (
                "Add beneficiary Stranger, account 999988887777, "
                "IFSC ICIC0000456, bank ICICI Bank"
            ),
            "conversation_id": thread_id,
        }
        events = list(graph.stream(init_state, config=config, stream_mode="updates"))
        assert any("__interrupt__" in e for e in events)

        # Step 2: User clicks REJECT
        resume_reject = Command(resume={"decision": "REJECT"})
        events_reject = list(graph.stream(resume_reject, config=config, stream_mode="updates"))

        # Verify execute was skipped
        executed_nodes = [next(iter(e.keys())) for e in events_reject]
        assert "execute" not in executed_nodes
        assert "response" in executed_nodes
        mock_banking_client.create_beneficiary.assert_not_called()

        # Check final checkpoint state
        state_final = graph.get_state(config).values
        assert state_final["approval_status"] == ApprovalStatus.REJECTED.value
        assert "cancelled" in state_final["response"].lower()
