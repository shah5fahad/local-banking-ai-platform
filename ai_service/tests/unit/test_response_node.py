"""Unit tests for the Response node and output guard (T4.5)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from app.agents.guards.output_guard import run_output_guard, sanitise_response
from app.agents.nodes.response import (
    INPUT_BLOCKED_PREFIX,
    OUT_OF_DOMAIN_RESPONSE,
    UNSUPPORTED_RESPONSE,
    response_node,
)
from app.agents.state import GraphState


def test_response_node_terminal_routes() -> None:
    # 1. Out of domain
    state_ood: GraphState = {"agent_route": "reject_out_of_domain"}
    res_ood = response_node(state_ood)
    assert res_ood["response"] == OUT_OF_DOMAIN_RESPONSE

    # 2. Unsupported
    state_uns: GraphState = {"agent_route": "unsupported"}
    res_uns = response_node(state_uns)
    assert res_uns["response"] == UNSUPPORTED_RESPONSE


def test_response_node_blocked_input_prefix() -> None:
    state: GraphState = {
        "input_blocked": True,
        "response": "Prompt injection detected.",
    }
    res = response_node(state)
    assert res["response"].startswith(INPUT_BLOCKED_PREFIX)
    assert "Prompt injection detected." in res["response"]


def test_response_node_composes_from_tool_results() -> None:
    state: GraphState = {
        "agent_route": "banking_ops",
        "user_message": "What is my balance?",
        "tool_results": [
            {
                "tool_name": "list_accounts",
                "result_masked": '{"accounts": [{"bank_name": "Test Bank", "account_number_masked": "XXXXXX1234"}]}',
                "success": True,
            }
        ],
        "messages": [],
    }

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(
        content="You have an active account at Test Bank ending in 1234."
    )

    with patch("app.agents.nodes.response.create_llm", return_value=fake_llm):
        res = response_node(state)

    assert "Test Bank ending in 1234" in res["response"]


def test_output_guard_masks_sensitive_data() -> None:
    # 16-digit card number masking
    text_with_card = "Your card number is 4111222233334444."
    sanitised = run_output_guard(text_with_card)
    assert "4111222233334444" not in sanitised
    assert "4444" in sanitised

    # Bearer token masking
    text_with_token = "Use this Bearer secret_token_xyz_123 to authenticate."
    sanitised_token = run_output_guard(text_with_token)
    assert "secret_token_xyz_123" not in sanitised_token


def test_output_guard_blocks_secret_requests() -> None:
    malicious_ai_response = "Please share your 4-digit PIN so I can complete this transfer."
    sanitised = run_output_guard(malicious_ai_response)
    assert "PIN" not in sanitised
    assert "issue generating a response" in sanitised
