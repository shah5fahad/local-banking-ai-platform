"""Transfer state machine - enforces valid transitions."""
from __future__ import annotations

from app.core.errors import ConflictError

VALID_TRANSITIONS: dict[str, set[str]] = {
    "PENDING_APPROVAL": {"AUTHORIZED", "CANCELLED", "EXPIRED"},
    "AUTHORIZED": {"PROCESSING", "CANCELLED"},
    "PROCESSING": {"COMPLETED", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
    "EXPIRED": set(),
}


def transition(current: str, target: str, context: str = "transfer") -> None:
    """Raise ConflictError if transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ConflictError(f"{context} cannot transition from {current} to {target}")
