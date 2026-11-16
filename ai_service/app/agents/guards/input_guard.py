"""Input guard: validate and sanitise user messages before passing to LLM.

Checks:
1. Max length (default 2000 chars)
2. Strip control characters (except newlines and tabs)
3. Injection heuristics: patterns that look like prompt injection attempts
4. PII/secret detector: message containing patterns like PIN numbers, JWT tokens,
   passwords → refuse to process and warn user (never store these)
5. Unicode normalisation to prevent homoglyph attacks
"""
from __future__ import annotations

import re
import unicodedata

MAX_MESSAGE_LENGTH = 2000

# Injection patterns (heuristic, not exhaustive)
_INJECTION_PATTERNS = [
    re.compile(r"ignore (previous|all|above) instructions", re.I),
    re.compile(r"disregard (your|the) (system|previous) (prompt|instructions)", re.I),
    re.compile(r"you are now.*(different|new|another) (ai|assistant|bot)", re.I),
    re.compile(r"(act|pretend|roleplay) as", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"</?(?:system|instructions?|prompt)>", re.I),
    re.compile(r"\[INST\]|\[/?SYS\]|<<SYS>>"),  # Llama-style injection
]

# Secret patterns - refuse if detected (never log the content)
_SECRET_PATTERNS = [
    re.compile(r"\bmy (pin|password|otp|secret) is\b", re.I),
    re.compile(r"password[:\s]+\S{6,}", re.I),
    re.compile(r"\b(pin|otp|password)[:\s=]+\S{4,}\b", re.I),
    re.compile(r"\bey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
]


def sanitise_message(text: str) -> str:
    """Strip control chars, normalise unicode."""
    # NFKC normalisation (handles homoglyphs)
    text = unicodedata.normalize("NFKC", text)
    # Remove control characters except newline and tab
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", text)
    return text.strip()


def check_injection(text: str) -> str | None:
    """Return injection pattern string if detected, else None."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def check_secrets(text: str) -> bool:
    """Return True if text looks like it contains a secret/credential."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return True
    return False


def validate_message(text: str) -> tuple[str, bool, str | None]:
    """Validate and sanitise a user message.

    Returns:
        (sanitised_text, is_blocked, block_reason)
    """
    # Length check
    if len(text) > MAX_MESSAGE_LENGTH:
        return text[:MAX_MESSAGE_LENGTH], True, f"Message too long (max {MAX_MESSAGE_LENGTH} chars)"

    sanitised = sanitise_message(text)

    # Secret detection
    if check_secrets(sanitised):
        return (
            "",
            True,
            "Your message appears to contain sensitive credentials. Please do not share passwords, PINs, or OTPs in chat.",
        )

    # Injection detection
    injection = check_injection(sanitised)
    if injection:
        return (
            "",
            True,
            "I cannot process this message as it contains patterns that may be attempting to manipulate my behavior.",
        )

    return sanitised, False, None
