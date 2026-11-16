"""Tests verifying the spec routing table passes 100% (T4.7 acceptance criteria)."""
from __future__ import annotations

import pytest

from app.agents.graph import build_graph
from app.agents.nodes.response import OUT_OF_DOMAIN_RESPONSE, UNSUPPORTED_RESPONSE
from app.agents.nodes.supervisor import classify_heuristically, supervisor_node
from app.agents.state import GraphState


SPEC_ROUTING_TABLE = [
    ("What is my account balance?", "BANK_READ", "banking_ops"),
    ("Show my last 10 transactions", "BANK_READ", "banking_ops"),
    ("Add a new beneficiary", "BENEFICIARY_ADD", "workflow_beneficiary"),
    ("Transfer ₹5,000 to Rahul", "TRANSFER", "workflow_transfer"),
    ("Show my pre-approved loans", "LOAN_INFO", "banking_ops"),
    ("Apply for a personal loan", "LOAN_APPLY", "workflow_loan"),
    ("What is the bank's loan policy?", "POLICY_QA", "policy_rag"),
    ("What is the RBI repo rate?", "EXTERNAL_INFO", "external_research"),
    ("Explain Python decorators", "OUT_OF_DOMAIN", "reject_out_of_domain"),
    ("What are my credit card dues?", "CARD_INFO", "banking_ops"),
    ("Pay my credit card bill", "CARD_PAYMENT", "workflow_card_payment"),
]


@pytest.mark.parametrize("query,expected_intent,expected_route", SPEC_ROUTING_TABLE)
def test_spec_routing_table_heuristic_classification(
    query: str, expected_intent: str, expected_route: str
) -> None:
    """AC: Verify every row in docs/agent_architecture.md §2 routing table classifies correctly."""
    result = classify_heuristically(query)
    assert result is not None, f"Failed to classify query: '{query}'"
    assert result.intent == expected_intent, f"Query '{query}' expected intent {expected_intent}, got {result.intent}"
    assert result.route == expected_route, f"Query '{query}' expected route {expected_route}, got {result.route}"


@pytest.mark.parametrize("query,expected_intent,expected_route", SPEC_ROUTING_TABLE)
def test_supervisor_node_routing_with_spec_table(
    query: str, expected_intent: str, expected_route: str
) -> None:
    """Verify supervisor_node classifies and applies deterministic overlay for all spec table queries."""
    state: GraphState = {"user_message": query}
    result = supervisor_node(state)
    assert result["intent"] == expected_intent
    assert result["agent_route"] == expected_route


def test_unsupported_banking_handling() -> None:
    """Verify unsupported banking features route to unsupported terminal node."""
    state: GraphState = {"user_message": "Can I order a physical checkbook?"}
    result = supervisor_node(state)
    assert result["intent"] == "UNSUPPORTED_BANKING"
    assert result["agent_route"] == "unsupported"


def test_end_to_end_graph_rejection_responses() -> None:
    """Verify out-of-domain and unsupported queries produce spec canned responses through the full graph."""
    graph = build_graph(checkpointer=None)
    config = {"configurable": {"thread_id": "test-t47-routing", "access_token": "mock-token"}}

    # Out of domain query
    ood_output = graph.invoke({"user_message": "Explain Python decorators"}, config=config)
    assert ood_output["intent"] == "OUT_OF_DOMAIN"
    assert ood_output["agent_route"] == "reject_out_of_domain"
    assert ood_output["response"] == OUT_OF_DOMAIN_RESPONSE

    # Unsupported query
    unsupported_output = graph.invoke({"user_message": "Can I order a physical checkbook?"}, config=config)
    assert unsupported_output["intent"] == "UNSUPPORTED_BANKING"
    assert unsupported_output["agent_route"] == "unsupported"
    assert unsupported_output["response"] == UNSUPPORTED_RESPONSE
