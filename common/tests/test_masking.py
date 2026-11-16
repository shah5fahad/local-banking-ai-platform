"""Unit tests for the MaskingFilter (T1.2 acceptance criteria)."""
import logging

import pytest

from banking_common.logging import MaskingFilter, _mask_string


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# JWT masking
# ---------------------------------------------------------------------------


SAMPLE_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiJ1c2VyLTEiLCJleHAiOjE3MDAwMDAwMDB9"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)


def test_jwt_in_message_is_masked() -> None:
    f = MaskingFilter()
    record = _make_record(f"Token issued: {SAMPLE_JWT}")
    f.filter(record)
    assert SAMPLE_JWT not in record.msg
    assert "[MASKED_TOKEN]" in record.msg


def test_jwt_header_prefix_still_visible_after_masking() -> None:
    """The word 'Token issued:' must remain; only the JWT value is gone."""
    f = MaskingFilter()
    record = _make_record(f"Token issued: {SAMPLE_JWT}")
    f.filter(record)
    assert "Token issued:" in record.msg


# ---------------------------------------------------------------------------
# Bearer token masking
# ---------------------------------------------------------------------------


def test_bearer_token_masked() -> None:
    f = MaskingFilter()
    record = _make_record(f"Authorization: Bearer {SAMPLE_JWT}")
    f.filter(record)
    assert SAMPLE_JWT not in record.msg
    assert "Bearer" in record.msg
    assert "[MASKED_TOKEN]" in record.msg


def test_bearer_token_case_insensitive() -> None:
    f = MaskingFilter()
    record = _make_record("authorization: bearer sometoken.part2.part3")
    f.filter(record)
    assert "sometoken" not in record.msg


# ---------------------------------------------------------------------------
# Card number masking
# ---------------------------------------------------------------------------


def test_card_number_spaced_masked() -> None:
    f = MaskingFilter()
    record = _make_record("Card 4111 1111 1111 1111 charged ₹500")
    f.filter(record)
    assert "1111 1111 1111" not in record.msg


def test_card_number_compact_masked() -> None:
    f = MaskingFilter()
    record = _make_record("Charged card 4111111111111111")
    f.filter(record)
    assert "4111111111111111" not in record.msg


# ---------------------------------------------------------------------------
# Sensitive field masking
# ---------------------------------------------------------------------------


def test_password_field_masked_on_record() -> None:
    f = MaskingFilter()
    record = _make_record("login attempt", password="secret123")
    f.filter(record)
    assert record.password == "[MASKED]"  # type: ignore[attr-defined]


def test_pin_field_masked_on_record() -> None:
    f = MaskingFilter()
    record = _make_record("pin verified", pin="1234")
    f.filter(record)
    assert record.pin == "[MASKED]"  # type: ignore[attr-defined]


def test_token_field_masked_on_record() -> None:
    f = MaskingFilter()
    record = _make_record("token stored", token=SAMPLE_JWT)
    f.filter(record)
    assert record.token == "[MASKED]"  # type: ignore[attr-defined]


def test_account_number_field_masked_on_record() -> None:
    f = MaskingFilter()
    record = _make_record("account fetched", account_number="123456789012")
    f.filter(record)
    assert record.account_number == "[MASKED]"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Normal messages pass through unchanged
# ---------------------------------------------------------------------------


def test_normal_message_unchanged() -> None:
    f = MaskingFilter()
    record = _make_record("User logged in successfully")
    f.filter(record)
    assert record.msg == "User logged in successfully"


def test_no_false_positive_on_short_numbers() -> None:
    """Short numbers like amounts should not be aggressively masked."""
    result = _mask_string("Transfer amount: 500")
    # 500 is 3 digits — should NOT be masked by PIN pattern (4-6 digits)
    assert "500" in result


# ---------------------------------------------------------------------------
# _mask_string helper
# ---------------------------------------------------------------------------


def test_mask_string_idempotent_on_already_masked() -> None:
    already = "Authorization: Bearer [MASKED_TOKEN]"
    assert _mask_string(already) == already


def test_mask_string_multiple_jwts() -> None:
    text = f"first={SAMPLE_JWT} second={SAMPLE_JWT}"
    result = _mask_string(text)
    assert SAMPLE_JWT not in result
    assert result.count("[MASKED_TOKEN]") == 2
