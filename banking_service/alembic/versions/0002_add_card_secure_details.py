"""add_card_secure_details

Revision ID: 0002_card_details
Revises: 0001_initial_schema
Create Date: 2026-11-16 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_card_details"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credit_cards", sa.Column("card_number_encrypted", sa.String(length=512), nullable=True))
    op.add_column("credit_cards", sa.Column("card_number_hash", sa.String(length=64), nullable=True))
    op.add_column("credit_cards", sa.Column("expiry_date", sa.String(length=7), nullable=True))
    op.add_column("credit_cards", sa.Column("cvv_encrypted", sa.String(length=256), nullable=True))
    op.add_column("credit_cards", sa.Column("cvv_hash", sa.String(length=256), nullable=True))
    op.create_index(op.f("ix_credit_cards_card_number_hash"), "credit_cards", ["card_number_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_credit_cards_card_number_hash"), table_name="credit_cards")
    op.drop_column("credit_cards", "cvv_hash")
    op.drop_column("credit_cards", "cvv_encrypted")
    op.drop_column("credit_cards", "expiry_date")
    op.drop_column("credit_cards", "card_number_hash")
    op.drop_column("credit_cards", "card_number_encrypted")
