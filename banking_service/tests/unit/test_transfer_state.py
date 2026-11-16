"""Unit tests for the transfer state machine (T2.8)."""
import pytest

from app.core.errors import ConflictError
from app.services.transfer_state import transition


class TestTransferStateMachine:
    def test_valid_transitions(self) -> None:
        # PENDING_APPROVAL -> AUTHORIZED
        transition("PENDING_APPROVAL", "AUTHORIZED")
        # PENDING_APPROVAL -> CANCELLED
        transition("PENDING_APPROVAL", "CANCELLED")
        # PENDING_APPROVAL -> EXPIRED
        transition("PENDING_APPROVAL", "EXPIRED")
        # AUTHORIZED -> PROCESSING
        transition("AUTHORIZED", "PROCESSING")
        # AUTHORIZED -> CANCELLED
        transition("AUTHORIZED", "CANCELLED")
        # PROCESSING -> COMPLETED
        transition("PROCESSING", "COMPLETED")
        # PROCESSING -> FAILED
        transition("PROCESSING", "FAILED")

    def test_illegal_transitions_raise_conflict(self) -> None:
        with pytest.raises(ConflictError):
            transition("PENDING_APPROVAL", "COMPLETED")

        with pytest.raises(ConflictError):
            transition("COMPLETED", "CANCELLED")

        with pytest.raises(ConflictError):
            transition("FAILED", "PROCESSING")

        with pytest.raises(ConflictError):
            transition("CANCELLED", "AUTHORIZED")
