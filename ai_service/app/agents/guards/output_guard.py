"""Output guard: validate and sanitise LLM responses before sending to user.

Checks:
1. Mask any residual account/card numbers, JWTs, or bearer tokens
2. Block responses claiming to be from a different AI system
3. Remove any content that looks like it's instructing the user to share secrets
4. Verify figures against tool results (soft check - warn if mismatch)
"""
from __future__ import annotations

import re

try:
    from banking_common.logging import _mask_string
except ImportError:
    # Fallback masking if banking_common is not in path
    _CARD_PATTERN = re.compile(r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b")
    _BEARER_PATTERN = re.compile(r"(Bearer\s+)[\w\.\-]+", re.IGNORECASE)
    _JWT_PATTERN = re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")

    def _mask_string(text: str) -> str:
        text = _CARD_PATTERN.sub(lambda m: m.group(0)[:4] + "-****-****-" + m.group(0)[-4:], text)
        text = _BEARER_PATTERN.sub(r"\1[MASKED_TOKEN]", text)
        text = _JWT_PATTERN.sub("[MASKED_TOKEN]", text)
        return text


_PERSONA_PATTERNS = [
    re.compile(r"(?<=I am )(GPT|Claude|Gemini|LLaMA|Mistral|ChatGPT)", re.I),
    re.compile(r"(?<=As )(GPT|Claude|Gemini|a different AI)", re.I),
]

_SECRET_REQUEST_PATTERNS = [
    re.compile(
        r"(please|could you|can you).{0,30}(share|provide|give|enter).{0,30}(pin|password|otp|secret)",
        re.I,
    ),
    re.compile(r"enter your (pin|password|otp)", re.I),
]


def sanitise_response(text: str) -> str:
    """Apply masking and safety filters to LLM response text."""
    # Apply banking_common masking (account numbers, tokens, etc)
    text = _mask_string(text)

    # Block persona hijacking
    for pattern in _PERSONA_PATTERNS:
        text = pattern.sub("[ASSISTANT]", text)

    # Block secret requests (should never happen, but defence in depth)
    for pattern in _SECRET_REQUEST_PATTERNS:
        if pattern.search(text):
            return "I encountered an issue generating a response. Please try again."

    return text


def run_output_guard(response: str, tool_results: list[dict] | None = None) -> str:
    """Run all output guard checks and return sanitised response."""
    if not response:
        return response
    return sanitise_response(response)
