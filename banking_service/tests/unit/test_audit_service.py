"""Unit tests for AuditService and hash chaining."""
from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.services.audit_service import AuditService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_audit_log_masking(db_session) -> None:
    details = {
        "account_number": "123456789012",
        "password": "SecretPassword123!",
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.sig",
        "safe_field": "hello world",
    }
    entry = AuditService.log(
        db=db_session,
        action="TEST_ACTION",
        outcome="SUCCESS",
        details=details,
    )
    db_session.commit()

    saved = json.loads(entry.details_json)
    assert saved["account_number"] == "[MASKED]"
    assert saved["password"] == "[MASKED]"
    assert saved["token"] == "[MASKED]"
    assert saved["safe_field"] == "hello world"


def test_audit_log_hash_chain(db_session) -> None:
    entry1 = AuditService.log(
        db=db_session,
        action="ACTION_1",
        outcome="SUCCESS",
    )
    db_session.commit()
    assert entry1.prev_hash is None
    assert entry1.hash is not None

    entry2 = AuditService.log(
        db=db_session,
        action="ACTION_2",
        outcome="SUCCESS",
    )
    db_session.commit()
    assert entry2.prev_hash == entry1.hash
    assert entry2.hash != entry1.hash
