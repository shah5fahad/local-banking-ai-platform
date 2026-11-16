"""Models package — imports all ORM models so Alembic autogenerate sees them.

Builder C's user.py contains User, Role, UserRole, Session in one file.
Builder A's session.py also exists; both define the same table so we import
from one authoritative source (user.py which is the latest).
"""
from __future__ import annotations

from app.db.base import Base  # noqa: F401

# User / auth
from app.models.user import Role, Session, User, UserRole  # noqa: F401

# Financial
from app.models.account import BankAccount  # noqa: F401
from app.models.beneficiary import Beneficiary  # noqa: F401
from app.models.approval_challenge import ApprovalChallenge  # noqa: F401
from app.models.transaction import BankTransaction, TransferAuthorization  # noqa: F401
from app.models.loan import LoanApplication, LoanOffer  # noqa: F401
from app.models.credit_card import CreditCard, CreditCardPayment, CreditCardStatement  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401

__all__ = [
    "Base",
    "User",
    "Role",
    "UserRole",
    "Session",
    "BankAccount",
    "Beneficiary",
    "ApprovalChallenge",
    "BankTransaction",
    "TransferAuthorization",
    "LoanOffer",
    "LoanApplication",
    "CreditCard",
    "CreditCardStatement",
    "CreditCardPayment",
    "AuditLog",
]
