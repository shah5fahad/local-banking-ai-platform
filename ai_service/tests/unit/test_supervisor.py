"""Unit tests for the supervisor node routing and deterministic overlays."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from app.agents.nodes.supervisor import supervisor_node
from app.agents.state import GraphState
from app.integrations.llm_factory import FakeChatModel, set_test_fake_llm


def test_routing_override_applied():
    # LLM incorrectly suggests route="banking_ops" for TRANSFER intent
    llm_payload = json.dumps(
        {
            "intent": "TRANSFER",
            "route": "banking_ops",  # incorrect suggestion by LLM
            "confidence": 0.95,
            "needs_api": True,
            "needs_docs": False,
            "needs_web": False,
        }
    )
    fake_llm = FakeChatModel(responses=[llm_payload])
    set_test_fake_llm(fake_llm)
    try:
        state: GraphState = {"user_message": "Transfer ₹5,000 to John"}
        result = supervisor_node(state)

        assert result["intent"] == "TRANSFER"
        # Deterministic override should enforce workflow_transfer
        assert result["agent_route"] == "workflow_transfer"
        assert result["route_confidence"] == 0.95
    finally:
        set_test_fake_llm(None)


def test_routing_override_for_policy_and_domain():
    tests = [
        ("POLICY_QA", "banking_ops", 0.9, "policy_rag"),
        ("BENEFICIARY_ADD", "unsupported", 0.85, "workflow_beneficiary"),
        ("OUT_OF_DOMAIN", "banking_ops", 0.99, "reject_out_of_domain"),
        ("LOAN_APPLY", "banking_ops", 0.9, "workflow_loan"),
        ("CARD_PAYMENT", "banking_ops", 0.92, "workflow_card_payment"),
    ]

    for intent, llm_route, conf, expected_route in tests:
        payload = json.dumps({"intent": intent, "route": llm_route, "confidence": conf})
        fake_llm = FakeChatModel(responses=[payload])
        set_test_fake_llm(fake_llm)
        try:
            state: GraphState = {"user_message": "test query"}
            result = supervisor_node(state)
            assert result["intent"] == intent
            assert result["agent_route"] == expected_route
        finally:
            set_test_fake_llm(None)


def test_low_confidence_routes_to_unsupported():
    # Confidence 0.35 is below LOW_CONFIDENCE_THRESHOLD (0.50)
    llm_payload = json.dumps(
        {
            "intent": "TRANSFER",
            "route": "workflow_transfer",
            "confidence": 0.35,
            "needs_api": True,
        }
    )
    fake_llm = FakeChatModel(responses=[llm_payload])
    set_test_fake_llm(fake_llm)
    try:
        state: GraphState = {"user_message": "Maybe send something?"}
        result = supervisor_node(state)

        assert result["intent"] == "TRANSFER"
        assert result["agent_route"] == "unsupported"
        assert result["route_confidence"] == 0.35
    finally:
        set_test_fake_llm(None)


def test_fallback_on_llm_error():
    # Test with invalid JSON / exception from LLM
    fake_llm = FakeChatModel(responses=["Not valid JSON at all!"])
    set_test_fake_llm(fake_llm)
    try:
        state: GraphState = {"user_message": "Hello"}
        result = supervisor_node(state)

        assert result["intent"] == "UNSUPPORTED_BANKING"
        assert result["agent_route"] == "unsupported"
        assert result["route_confidence"] == 0.0
    finally:
        set_test_fake_llm(None)


def test_markdown_codeblock_parsing():
    # LLM wraps JSON in ```json ... ``` markdown code fence
    llm_payload = """```json
    {
        "intent": "BANK_READ",
        "route": "banking_ops",
        "confidence": 0.9
    }
    ```"""
    fake_llm = FakeChatModel(responses=[llm_payload])
    set_test_fake_llm(fake_llm)
    try:
        state: GraphState = {"user_message": "Check balance"}
        result = supervisor_node(state)

        assert result["intent"] == "BANK_READ"
        assert result["agent_route"] == "banking_ops"
        assert result["route_confidence"] == 0.9
    finally:
        set_test_fake_llm(None)
