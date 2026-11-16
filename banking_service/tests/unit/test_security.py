"""Unit tests for app.core.security module."""
from __future__ import annotations

import time
import pytest

from app.core.config import BankingSettings
from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_field,
    encrypt_field,
    get_encryption_key,
    hash_password,
    hash_token,
    hmac_field,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    plain = "SuperSecret123!"
    hashed = hash_password(plain)
    assert hashed.startswith("$argon2id$")
    assert verify_password(plain, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_hash_token() -> None:
    token = "some-random-refresh-token"
    h1 = hash_token(token)
    h2 = hash_token(token)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_field_encryption_decryption() -> None:
    settings = BankingSettings(field_encryption_key="test-secret-key-32-chars-long!")
    key = get_encryption_key(settings)
    assert len(key) == 32

    account_no = "123456789012"
    encrypted = encrypt_field(account_no, key)
    assert encrypted != account_no
    decrypted = decrypt_field(encrypted, key)
    assert decrypted == account_no


def test_hmac_field() -> None:
    settings = BankingSettings(field_encryption_key="test-key")
    key = get_encryption_key(settings)
    val = "123456789012"
    h1 = hmac_field(val, key)
    h2 = hmac_field(val, key)
    assert h1 == h2
    assert len(h1) == 64


def test_jwt_access_token_creation_and_decoding() -> None:
    settings = BankingSettings(
        jwt_secret="a-very-long-test-jwt-secret-key-min-32-chars",
        access_token_expire_minutes=15,
    )
    token, jti = create_access_token(
        sub="user-123",
        roles=["CUSTOMER"],
        sid="session-456",
        settings=settings,
    )
    assert token
    assert jti

    payload = decode_access_token(token, settings)
    assert payload["sub"] == "user-123"
    assert payload["roles"] == ["CUSTOMER"]
    assert payload["sid"] == "session-456"
    assert payload["jti"] == jti


def test_jwt_invalid_or_expired() -> None:
    settings = BankingSettings(jwt_secret="a-very-long-test-jwt-secret-key-min-32-chars")
    with pytest.raises(UnauthorizedError):
        decode_access_token("invalid.jwt.token", settings)
