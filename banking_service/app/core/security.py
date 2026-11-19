"""Security utilities for the Banking service: Argon2 password/PIN hashing, JWT handling, AES-GCM."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt

from app.core.config import BankingSettings, get_settings
from app.core.errors import UnauthorizedError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an Argon2 hash."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def hash_pin(pin: str) -> str:
    """Hash a transaction PIN using Argon2."""
    return _ph.hash(pin)


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """Verify a transaction PIN against an Argon2 hash."""
    try:
        return _ph.verify(hashed_pin, plain_pin)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def sha256_hash(data: str) -> str:
    """Compute hex SHA-256 hash of a string."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    """Compute hex SHA-256 hash of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_key(key: str | bytes) -> bytes:
    if isinstance(key, str):
        key = key.encode("utf-8")
    if len(key) == 32:
        return key
    return hashlib.sha256(key).digest()


def get_encryption_key(settings: BankingSettings | None = None) -> bytes:
    """Derive 32-byte encryption key from settings."""
    if settings is None:
        settings = get_settings()
    raw = getattr(settings, "field_encryption_key", None) or getattr(settings, "jwt_secret", "")
    return _normalize_key(raw)


def encrypt_field(value: str, key: str | bytes) -> str:
    """Encrypt a string value using AES-GCM and return base64 string."""
    key_bytes = _normalize_key(key)
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("utf-8")


def decrypt_field(encrypted_value: str, key: str | bytes) -> str:
    """Decrypt a base64 encoded AES-GCM string."""
    key_bytes = _normalize_key(key)
    raw = base64.b64decode(encrypted_value.encode("utf-8"))
    nonce = raw[:12]
    ct = raw[12:]
    aesgcm = AESGCM(key_bytes)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")


def hmac_field(value: str, key: str | bytes) -> str:
    """Compute HMAC-SHA256 for a field value for deterministic lookup/hashing."""
    key_bytes = _normalize_key(key)
    return hmac.new(key_bytes, value.encode("utf-8"), hashlib.sha256).hexdigest()


def create_access_token(
    data: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
    *,
    sub: str | None = None,
    roles: list[str] | None = None,
    sid: str | None = None,
    jti: str | None = None,
    settings: BankingSettings | None = None,
    **kwargs: Any,
) -> tuple[str, str]:
    """Create a signed JWT access token and return (token, jti)."""
    if settings is None:
        settings = get_settings()
    to_encode = (data or {}).copy()
    to_encode.update(kwargs)
    if sub is not None:
        to_encode["sub"] = sub
    if roles is not None:
        to_encode["roles"] = roles
    if sid is not None:
        to_encode["sid"] = sid

    token_jti = jti or str(uuid.uuid4())
    to_encode["jti"] = token_jti

    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"iat": now, "exp": expire})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return str(encoded_jwt), token_jti


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
    settings: BankingSettings | None = None,
) -> str:
    """Create a signed JWT refresh token."""
    if settings is None:
        settings = get_settings()
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"iat": now, "exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return str(encoded_jwt)


def decode_token(token: str, settings: BankingSettings | None = None) -> dict[str, Any]:
    """Decode and validate a JWT token."""
    if settings is None:
        settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return dict(payload)
    except JWTError as e:
        raise UnauthorizedError(f"Invalid or expired token: {str(e)}") from e


decode_access_token = decode_token


def mask_account_number(last4: str) -> str:
    """Format masked account number: XXXXXX1234."""
    clean_last4 = last4[-4:] if len(last4) >= 4 else last4.rjust(4, "X")
    return f"XXXXXX{clean_last4}"


def mask_card_number(last4: str) -> str:
    """Format masked card number: XXXX-XXXX-XXXX-1234."""
    clean_last4 = last4[-4:] if len(last4) >= 4 else last4.rjust(4, "X")
    return f"XXXX-XXXX-XXXX-{clean_last4}"


def to_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime object is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

