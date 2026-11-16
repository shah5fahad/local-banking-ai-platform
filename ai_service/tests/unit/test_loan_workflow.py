"""Comprehensive unit and integration tests for Phase 5 task T5.4: Loan workflow.

Covers:
- Field parsing: loan type (Personal, Home, Auto), tenure (months/years), amount, income (paise, lakhs)
- Employment & employer extraction: salaried, self-employed, employer names
- Reducing balance EMI calculation
- Multi-turn conversational parameter extraction from history
- Missing field prompts (all fields, missing amount, missing tenure, missing income)
- Pre-approved loan offers presentation
- Eligibility evaluation via BankingClient (eligible vs ineligible with reason breakdown)
- Error handling during eligibility check (BankingClientError and generic exceptions)
- Execute node: approved loan application submission, reference tracking
- Execute node: error handling (BankingClientError, unexpected exceptions)
- End-to-end LangGraph HITL: prompt → interrupt(CONFIRM) → resume(CONFIRM) → execute
- Rejection flow: prompt → interrupt(CONFIRM) → REJECT → no execute, clean cancellation
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
from app.agents.workflows.loan import (
    calculate_emi_minor,
    extract_employment_and_employer,
    extract_loan_fields,
    parse_income_to_minor,
    parse_loan_amount_to_minor,
    parse_loan_type,
    parse_tenure_months,
    workflow_loan_node,
)
from app.integrations.banking_client import BankingClientError
from app.models.approval import ApprovalStatus, WorkflowType

# ============================================================================
# 1. Parsing & Helper Unit Tests
# ============================================================================


def test_parse_loan_type() -> None:
    assert parse_loan_type("Apply for a personal loan") == "PERSONAL"
    assert parse_loan_type("I need a home loan for my apartment") == "HOME"
    assert parse_loan_type("Need housing loan") == "HOME"
    assert parse_loan_type("Looking for a car loan") == "AUTO"
    assert parse_loan_type("Two-wheeler vehicle loan") == "AUTO"
    assert parse_loan_type("I want to borrow money") == "PERSONAL"


def test_parse_tenure_months() -> None:
    assert parse_tenure_months("for 24 months") == 24
    assert parse_tenure_months("tenure 36 mths") == 36
    assert parse_tenure_months("tenure: 12") == 12
    assert parse_tenure_months("for 2 years") == 24
    assert parse_tenure_months("5 yrs duration") == 60
    assert parse_tenure_months("no tenure mentioned") is None


def test_parse_income_to_minor() -> None:
    assert parse_income_to_minor("monthly income of ₹50,000") == 5000000
    assert parse_income_to_minor("salary 75000 per month") == 7500000
    assert parse_income_to_minor("earning ₹1,00,000 monthly") == 10000000
    assert parse_income_to_minor("salary 2 lakhs per month") == 20000000
    assert parse_income_to_minor("income: 60000") == 6000000
    assert parse_income_to_minor("I want a loan") is None


def test_parse_loan_amount_to_minor() -> None:
    assert parse_loan_amount_to_minor("Apply for a personal loan of ₹2,00,000") == 20000000
    assert parse_loan_amount_to_minor("loan of 5 lakhs for 2 years") == 50000000
    assert parse_loan_amount_to_minor("borrow ₹50,000") == 5000000
    assert parse_loan_amount_to_minor("amount: 300000") == 30000000
    # Ignores income if supplied
    assert (
        parse_loan_amount_to_minor(
            "loan of ₹2,00,000 with salary ₹50,000", monthly_income_minor=5000000
        )
        == 20000000
    )


def test_extract_employment_and_employer() -> None:
    emp_type, employer = extract_employment_and_employer("salaried at Google Inc")
    assert emp_type == "SALARIED"
    assert "Google" in employer

    emp_type, employer = extract_employment_and_employer("I am self-employed freelancer")
    assert emp_type == "SELF_EMPLOYED"
    assert employer == "Self-Employed"

    emp_type, employer = extract_employment_and_employer("business owner working at Acme Corp")
    assert emp_type == "BUSINESS"
    assert "Acme" in employer


def test_calculate_emi_minor() -> None:
    # Rs 2,00,000 (20,000,000 minor) at 12% (1200 bps) for 24 months
    emi = calculate_emi_minor(20000000, 1200, 24)
    # Reducing balance EMI for 200k at 12% for 24 mos is approx Rs 9,415 = 941,500 paise
    assert 940000 <= emi <= 943000

    # Zero tenure returns principal
    assert calculate_emi_minor(100000, 1200, 0) == 100000
    # Zero rate
    assert calculate_emi_minor(120000, 0, 12) == 10000


def test_extract_loan_fields_conversational_history() -> None:
    history = [
        HumanMessage(content="I want to apply for a personal loan"),
        AIMessage(content="How much would you like to borrow?"),
        HumanMessage(content="₹3,00,000 for 36 months"),
        AIMessage(content="What is your monthly income?"),
    ]
    curr = "My monthly income is ₹70,000 and I work at TCS"
    extracted = extract_loan_fields(curr, history)

    assert extracted["loan_type"] == "PERSONAL"
    assert extracted["amount_minor"] == 30000000
    assert extracted["tenure_months"] == 36
    assert extracted["monthly_income_minor"] == 7000000
    assert extracted["employment_type"] == "SALARIED"
    assert "TCS" in extracted["employer"]


# ============================================================================
# 2. Missing Field Prompts & Offers Presentation
# ============================================================================


def test_workflow_loan_missing_all_with_preapproved_offers() -> None:
    state: GraphState = {"user_message": "I want to apply for a loan"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    offers = [
        {
            "id": "offer-p-01",
            "loan_type": "PERSONAL",
            "max_amount_minor": 50000000,
            "rate_bps": 1150,
            "min_tenure_months": 12,
            "max_tenure_months": 60,
            "status": "ACTIVE",
        }
    ]

    with patch("app.agents.workflows.loan.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_loan_offers.return_value = offers

        res = workflow_loan_node(state, config=config)

    assert "pending_action" not in res
    assert res["approval_status"] == "NONE"
    assert "pre-approved" in res["response"].lower()
    assert "₹5,00,000.00" in res["response"]
    assert "11.50%" in res["response"]


def test_workflow_loan_missing_all_without_offers() -> None:
    state: GraphState = {"user_message": "Apply for a loan"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    with patch("app.agents.workflows.loan.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_loan_offers.return_value = []

        res = workflow_loan_node(state, config=config)

    assert "pending_action" not in res
    assert res["approval_status"] == "NONE"
    assert "specify the loan type" in res["response"].lower() or "amount" in res["response"].lower()


def test_workflow_loan_missing_tenure_prompt() -> None:
    state: GraphState = {"user_message": "Apply for a personal loan of ₹2,00,000"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    with patch("app.agents.workflows.loan.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_loan_offers.return_value = []

        res = workflow_loan_node(state, config=config)

    assert "pending_action" not in res
    assert "tenure" in res["response"].lower()


def test_workflow_loan_missing_income_prompt() -> None:
    state: GraphState = {"user_message": "Apply for a personal loan of ₹2,00,000 for 24 months"}
    config = {"configurable": {"access_token": "mock-jwt"}}

    with patch("app.agents.workflows.loan.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_loan_offers.return_value = []

        res = workflow_loan_node(state, config=config)

    assert "pending_action" not in res
    assert "monthly income" in res["response"].lower()


def test_workflow_loan_no_access_token() -> None:
    state: GraphState = {"user_message": "Apply for a loan"}
    res = workflow_loan_node(state, config={"configurable": {}})
    assert res.get("error_code") == "UNAUTHENTICATED"
    assert "log in" in res["response"].lower() or "session is missing" in res["response"].lower()


# ============================================================================
# 3. Eligibility Checks & Failures
# ============================================================================


def test_workflow_loan_ineligible_returns_reasons() -> None:
    state: GraphState = {
        "user_message": (
            "Apply for a personal loan of ₹4,00,000 for 12 months with monthly income ₹20,000"
        )
    }
    config = {"configurable": {"access_token": "mock-jwt"}}

    with patch("app.agents.workflows.loan.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_loan_offers.return_value = []
        mock_instance.check_loan_eligibility.return_value = {
            "eligible": False,
            "max_amount_minor": 50000000,
            "reasons": ["Estimated EMI exceeds 40% of monthly income."],
        }

        res = workflow_loan_node(state, config=config)

    assert "pending_action" not in res
    assert res["approval_status"] == "NONE"
    assert "unable to process" in res["response"].lower() or "not currently eligible" in res["response"].lower()
    assert "Estimated EMI exceeds 40%" in res["response"]


def test_workflow_loan_eligibility_banking_client_error() -> None:
    state: GraphState = {
        "user_message": "Apply for ₹2,00,000 personal loan for 24 months, monthly income ₹50,000"
    }
    config = {"configurable": {"access_token": "mock-jwt"}}

    with patch("app.agents.workflows.loan.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_loan_offers.return_value = []
        mock_instance.check_loan_eligibility.side_effect = BankingClientError(
            "ELIGIBILITY_FAILED", "Credit score check unavailable", 503
        )

        res = workflow_loan_node(state, config=config)

    assert "pending_action" not in res
    assert res.get("error_code") == "ELIGIBILITY_FAILED"
    assert "unable to check loan eligibility" in res["response"].lower()


def test_workflow_loan_eligibility_generic_exception() -> None:
    state: GraphState = {
        "user_message": "Apply for ₹2,00,000 personal loan for 24 months, monthly income ₹50,000"
    }
    config = {"configurable": {"access_token": "mock-jwt"}}

    with patch("app.agents.workflows.loan.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_loan_offers.return_value = []
        mock_instance.check_loan_eligibility.side_effect = RuntimeError("Service crashed")

        res = workflow_loan_node(state, config=config)

    assert "pending_action" not in res
    assert res.get("error_code") == "ELIGIBILITY_CHECK_FAILED"
    assert "unable to check loan eligibility" in res["response"].lower()


# ============================================================================
# 4. Successful Draft Preparation
# ============================================================================


def test_workflow_loan_eligible_prepares_pending_action() -> None:
    state: GraphState = {
        "user_message": (
            "Apply for a personal loan of ₹2,00,000 for 24 months, "
            "monthly income ₹60,000 at Infosys"
        )
    }
    config = {"configurable": {"access_token": "mock-jwt"}}

    offers = [
        {
            "id": "offer-pers-special",
            "loan_type": "PERSONAL",
            "max_amount_minor": 50000000,
            "rate_bps": 1050,  # 10.50% special pre-approved rate
            "status": "ACTIVE",
        }
    ]

    with patch("app.agents.workflows.loan.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.list_loan_offers.return_value = offers
        mock_instance.check_loan_eligibility.return_value = {
            "eligible": True,
            "max_amount_minor": 50000000,
            "reasons": [],
        }

        res = workflow_loan_node(state, config=config)

    assert "pending_action" in res
    pa: PendingAction = res["pending_action"]
    assert pa["workflow"] == WorkflowType.LOAN.value
    assert pa["banking_resource_id"] == "offer-pers-special"
    assert pa["stage"] == "CONFIRM"
    assert pa["summary_hash"] is not None

    summary = pa["summary_masked"]
    assert summary["loan_type"] == "Personal Loan"
    assert summary["amount"] == "₹2,00,000.00"
    assert summary["tenure"] == "24 months"
    assert "10.50%" in summary["interest_rate"]
    assert summary["monthly_income"] == "₹60,000.00"
    assert "Infosys" in summary["employment"]

    assert res["approval_status"] == ApprovalStatus.PENDING.value
    assert "review your loan application" in res["response"].lower()
    assert "₹2,00,000.00" in res["response"]


# ============================================================================
# 5. Execute Node – Loan Branch Tests
# ============================================================================


def _make_loan_state(
    approval_status: str = ApprovalStatus.CONFIRMED.value,
) -> GraphState:
    return {
        "pending_action": {
            "workflow": WorkflowType.LOAN.value,
            "banking_resource_id": "offer-pers-special",
            "summary_masked": {
                "loan_type": "Personal Loan",
                "amount": "₹2,00,000.00",
                "tenure": "24 months",
                "interest_rate": "10.50% p.a.",
                "estimated_emi": "₹9,279.00",
                "monthly_income": "₹60,000.00",
                "employment": "SALARIED (Infosys)",
            },
            "summary_hash": "hash-loan-123",
            "stage": "CONFIRM",
            "action_data": {
                "offer_id": "offer-pers-special",
                "loan_type": "PERSONAL",
                "amount_minor": 20000000,
                "tenure_months": 24,
                "employment_type": "SALARIED",
                "employer": "Infosys",
                "monthly_income_minor": 6000000,
                "summary_hash": "hash-loan-123",
                "idempotency_key": "loan-idem-001",
            },
        },
        "approval_status": approval_status,
        "authentication_status": "NONE",
    }


def test_execute_node_loan_approved() -> None:
    state = _make_loan_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.submit_loan_application.return_value = {
            "id": "loan-app-999",
            "reference": "REF-LOAN-999",
            "loan_type": "PERSONAL",
            "amount_minor": 20000000,
            "status": "APPROVED",
            "decision_reason": "Instant approval based on credit profile",
        }

        out = execute_node(state, config=config)

    assert out["approval_status"] == ApprovalStatus.EXECUTED.value
    assert out["transaction_reference"] == "REF-LOAN-999"
    assert out["pending_action"] is None
    assert "congratulations" in out["response"].lower()
    assert "approved" in out["response"].lower()
    assert "REF-LOAN-999" in out["response"]
    assert "₹2,00,000.00" in out["response"]

    mock_instance.submit_loan_application.assert_called_once_with(
        {
            "offer_id": "offer-pers-special",
            "loan_type": "PERSONAL",
            "amount_minor": 20000000,
            "tenure_months": 24,
            "employment_type": "SALARIED",
            "employer": "Infosys",
            "monthly_income_minor": 6000000,
        },
        idempotency_key="loan-idem-001",
    )


def test_execute_node_loan_submitted_under_review() -> None:
    state = _make_loan_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.submit_loan_application.return_value = {
            "id": "loan-app-review",
            "reference": "REF-LOAN-REV",
            "loan_type": "PERSONAL",
            "amount_minor": 20000000,
            "status": "SUBMITTED",
            "decision_reason": "Manual underwriter verification required",
        }

        out = execute_node(state, config=config)

    assert out["approval_status"] == ApprovalStatus.EXECUTED.value
    assert out["transaction_reference"] == "REF-LOAN-REV"
    assert "submitted" in out["response"].lower()
    assert "Manual underwriter verification" in out["response"]


def test_execute_node_loan_banking_client_error() -> None:
    state = _make_loan_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.submit_loan_application.side_effect = BankingClientError(
            "DUPLICATE_APPLICATION", "An application is already active", 409
        )

        out = execute_node(state, config=config)

    assert out.get("error_code") == "DUPLICATE_APPLICATION"
    assert "failed to submit loan application" in out["response"].lower()


def test_execute_node_loan_generic_exception() -> None:
    state = _make_loan_state()
    config = {"configurable": {"access_token": "user-jwt"}}

    with patch("app.agents.nodes.execute.BankingClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.submit_loan_application.side_effect = RuntimeError("Network error")

        out = execute_node(state, config=config)

    assert out.get("error_code") == "EXECUTION_FAILED"
    assert "failed to submit loan application" in out["response"].lower()


# ============================================================================
# 6. End-to-End LangGraph HITL Integration Tests
# ============================================================================


def _build_loan_mock_client() -> MagicMock:
    mock = MagicMock()
    mock.list_loan_offers.return_value = [
        {
            "id": "offer-preapp-01",
            "loan_type": "PERSONAL",
            "max_amount_minor": 50000000,
            "rate_bps": 1100,
            "status": "ACTIVE",
        }
    ]
    mock.check_loan_eligibility.return_value = {
        "eligible": True,
        "max_amount_minor": 50000000,
        "reasons": [],
    }
    mock.submit_loan_application.return_value = {
        "id": "app-hitl-001",
        "reference": "REF-HITL-LOAN-001",
        "loan_type": "PERSONAL",
        "amount_minor": 20000000,
        "status": "APPROVED",
        "decision_reason": "Instant approval",
    }
    return mock


def test_end_to_end_loan_approval_and_execution() -> None:
    """Full HITL flow for Loan: prompt → interrupt(CONFIRM) → resume(CONFIRM) → execute."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread_id = "thread-loan-hitl-01"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "user-access-token-jwt",
        }
    }

    mock_client = _build_loan_mock_client()

    with (
        patch("app.agents.workflows.loan.BankingClient", return_value=mock_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        # Step 1: Initial user message with loan parameters
        init_state = {
            "user_message": "Apply for a personal loan of ₹2,00,000 for 24 months with monthly income ₹50,000",
            "conversation_id": thread_id,
        }
        events = list(graph.stream(init_state, config=config, stream_mode="updates"))

        # Must pause at Stage 1 interrupt (CONFIRM)
        interrupt_events = [e for e in events if "__interrupt__" in e]
        assert len(interrupt_events) == 1
        interrupt_val = interrupt_events[0]["__interrupt__"][0].value
        assert interrupt_val["stage"] == "CONFIRM"
        assert interrupt_val["workflow"] == "LOAN"
        assert interrupt_val["summary"]["amount"] == "₹2,00,000.00"
        assert interrupt_val["summary"]["tenure"] == "24 months"

        # Verify eligibility check was called
        mock_client.check_loan_eligibility.assert_called_once()
        # Verify submit was NOT called yet
        mock_client.submit_loan_application.assert_not_called()

        # Step 2: User confirms → resumes directly to execute (no MFA required for loans)
        events_resume = list(
            graph.stream(Command(resume={"decision": "CONFIRM"}), config=config, stream_mode="updates")
        )

        executed_nodes = [next(iter(e.keys())) for e in events_resume]
        assert "execute" in executed_nodes
        assert "response" in executed_nodes

        # Backend application submit was called
        mock_client.submit_loan_application.assert_called_once()
        call_payload = mock_client.submit_loan_application.call_args[0][0]
        assert call_payload["loan_type"] == "PERSONAL"
        assert call_payload["amount_minor"] == 20000000
        assert call_payload["tenure_months"] == 24

        # Final checkpoint state
        final_state = graph.get_state(config).values
        assert final_state["approval_status"] == ApprovalStatus.EXECUTED.value
        assert final_state["transaction_reference"] == "REF-HITL-LOAN-001"
        assert "approved" in final_state["response"].lower()
        assert "REF-HITL-LOAN-001" in final_state["response"]


def test_end_to_end_loan_rejection_flow() -> None:
    """Rejection flow for Loan: user clicks REJECT at CONFIRM → no backend submit, clean cancellation."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread_id = "thread-loan-reject-01"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": "user-access-token-jwt",
        }
    }

    mock_client = _build_loan_mock_client()

    with (
        patch("app.agents.workflows.loan.BankingClient", return_value=mock_client),
        patch("app.agents.nodes.execute.BankingClient", return_value=mock_client),
    ):
        # Step 1: User requests loan
        init_state = {
            "user_message": "Apply for a personal loan of ₹2,00,000 for 24 months with monthly income ₹50,000",
            "conversation_id": thread_id,
        }
        events = list(graph.stream(init_state, config=config, stream_mode="updates"))
        assert any("__interrupt__" in e for e in events)

        # Step 2: User rejects
        events_reject = list(
            graph.stream(
                Command(resume={"decision": "REJECT"}),
                config=config,
                stream_mode="updates",
            )
        )
        rejected_nodes = [next(iter(e.keys())) for e in events_reject]

        # execute must NOT be reached
        assert "execute" not in rejected_nodes
        assert "response" in rejected_nodes

        # submit_loan_application must NOT be called
        mock_client.submit_loan_application.assert_not_called()

        # Final checkpoint state
        final_state = graph.get_state(config).values
        assert final_state["approval_status"] == ApprovalStatus.REJECTED.value
        assert "cancelled" in final_state["response"].lower()
