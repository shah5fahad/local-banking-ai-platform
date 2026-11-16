"""Unit tests for output guard sanitisation, masking, and persona blocking."""
from __future__ import annotations

from app.agents.guards.output_guard import run_output_guard, sanitise_response


def test_card_number_masked():
    text = "Your card number is 4111 2222 3333 4444."
    result = sanitise_response(text)
    assert "4111-****-****-4444" in result
    assert "4111 2222 3333 4444" not in result


def test_bearer_token_masked():
    text = "Headers: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abcd"
    result = sanitise_response(text)
    assert "[MASKED_TOKEN]" in result


def test_persona_hijacking_blocked():
    text = "I am GPT developed by OpenAI."
    result = sanitise_response(text)
    assert "I am [ASSISTANT] developed by OpenAI." in result


def test_secret_request_blocked():
    text = "To proceed, please enter your PIN and password."
    result = run_output_guard(text)
    assert "I encountered an issue generating a response" in result


def test_clean_response_unchanged():
    text = "Your account balance for Savings Account ending in 1234 is ₹1,50,000."
    result = run_output_guard(text)
    assert result == text
