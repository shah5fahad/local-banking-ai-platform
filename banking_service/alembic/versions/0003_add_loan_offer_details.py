"""add_loan_offer_details

Revision ID: 0003_loan_offer_details
Revises: 0002_card_details
Create Date: 2026-11-16 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_loan_offer_details"
down_revision: str | None = "0002_card_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("loan_offers", sa.Column("name", sa.String(length=128), nullable=True))
    op.add_column("loan_offers", sa.Column("terms", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("loan_offers", "terms")
    op.drop_column("loan_offers", "name")
