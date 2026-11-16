"""0001_initial_schema

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-11-10 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_action_ts", "audit_logs", ["action", "ts"], unique=False)
    op.create_index("ix_audit_logs_actor_ts", "audit_logs", ["actor_user_id", "ts"], unique=False)
    op.create_index(op.f("ix_audit_logs_actor_user_id"), "audit_logs", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_ts"), "audit_logs", ["ts"], unique=False)

    # 2. roles
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)

    # 3. users
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("transaction_pin_hash", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_phone"), "users", ["phone"], unique=True)

    # 4. approval_challenge
    op.create_table(
        "approval_challenge",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("pin_hash", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("approval_token_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_challenge_approval_token_hash"), "approval_challenge", ["approval_token_hash"], unique=False)
    op.create_index(op.f("ix_approval_challenge_user_id"), "approval_challenge", ["user_id"], unique=False)

    # 5. bank_accounts
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("holder_name", sa.String(length=255), nullable=False),
        sa.Column("account_number_encrypted", sa.String(length=512), nullable=False),
        sa.Column("account_number_last4", sa.String(length=4), nullable=False),
        sa.Column("account_number_hash", sa.String(length=64), nullable=False),
        sa.Column("ifsc", sa.String(length=11), nullable=False),
        sa.Column("bank_name", sa.String(length=128), nullable=False),
        sa.Column("branch_name", sa.String(length=128), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("balance_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "account_number_hash", name="uq_user_account_hash"),
    )
    op.create_index(op.f("ix_bank_accounts_user_id"), "bank_accounts", ["user_id"], unique=False)

    # 6. beneficiaries
    op.create_table(
        "beneficiaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("nickname", sa.String(length=128), nullable=True),
        sa.Column("account_number_encrypted", sa.String(length=512), nullable=False),
        sa.Column("last4", sa.String(length=4), nullable=False),
        sa.Column("account_hash", sa.String(length=64), nullable=False),
        sa.Column("ifsc", sa.String(length=11), nullable=False),
        sa.Column("bank_name", sa.String(length=128), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "account_hash", "ifsc", name="uq_user_beneficiary_account"),
    )
    op.create_index(op.f("ix_beneficiaries_user_id"), "beneficiaries", ["user_id"], unique=False)

    # 7. credit_cards
    op.create_table(
        "credit_cards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("card_token", sa.String(length=128), nullable=False),
        sa.Column("last4", sa.String(length=4), nullable=False),
        sa.Column("network", sa.String(length=32), nullable=False),
        sa.Column("credit_limit_minor", sa.BigInteger(), nullable=False),
        sa.Column("outstanding_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_cards_user_id"), "credit_cards", ["user_id"], unique=False)

    # 8. loan_offers
    op.create_table(
        "loan_offers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("loan_type", sa.String(length=32), nullable=False),
        sa.Column("max_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("rate_bps", sa.Integer(), nullable=False),
        sa.Column("min_tenure_months", sa.Integer(), nullable=False),
        sa.Column("max_tenure_months", sa.Integer(), nullable=False),
        sa.Column("valid_till", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_loan_offers_user_id"), "loan_offers", ["user_id"], unique=False)

    # 9. sessions
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_refresh_token_hash"), "sessions", ["refresh_token_hash"], unique=True)
    op.create_index(op.f("ix_sessions_revoked_at"), "sessions", ["revoked_at"], unique=False)
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)

    # 10. user_roles
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    # 11. bank_transactions
    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_account_id", sa.String(length=36), nullable=True),
        sa.Column("beneficiary_id", sa.String(length=36), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_debit_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("summary_hash", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["beneficiary_id"], ["beneficiaries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_account_id"], ["bank_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_user_txn_idempotency"),
    )
    op.create_index(op.f("ix_bank_transactions_beneficiary_id"), "bank_transactions", ["beneficiary_id"], unique=False)
    op.create_index(op.f("ix_bank_transactions_reference"), "bank_transactions", ["reference"], unique=True)
    op.create_index("ix_bank_transactions_user_created", "bank_transactions", ["user_id", "created_at"], unique=False)
    op.create_index(op.f("ix_bank_transactions_user_id"), "bank_transactions", ["user_id"], unique=False)
    op.create_index("ix_bank_transactions_user_status", "bank_transactions", ["user_id", "status"], unique=False)

    # 12. credit_card_statements
    op.create_table(
        "credit_card_statements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_due_minor", sa.BigInteger(), nullable=False),
        sa.Column("min_due_minor", sa.BigInteger(), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["credit_cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_card_statements_card_id"), "credit_card_statements", ["card_id"], unique=False)

    # 13. loan_applications
    op.create_table(
        "loan_applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("offer_id", sa.String(length=36), nullable=True),
        sa.Column("loan_type", sa.String(length=32), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("tenure_months", sa.Integer(), nullable=False),
        sa.Column("rate_bps", sa.Integer(), nullable=False),
        sa.Column("employment_type", sa.String(length=64), nullable=False),
        sa.Column("employer", sa.String(length=255), nullable=False),
        sa.Column("monthly_income_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision_reason", sa.String(length=512), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["loan_offers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_user_loan_idempotency"),
    )
    op.create_index(op.f("ix_loan_applications_reference"), "loan_applications", ["reference"], unique=True)
    op.create_index(op.f("ix_loan_applications_user_id"), "loan_applications", ["user_id"], unique=False)

    # 14. credit_card_payments
    op.create_table(
        "credit_card_payments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.Column("statement_id", sa.String(length=36), nullable=True),
        sa.Column("source_account_id", sa.String(length=36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("transaction_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["credit_cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["statement_id"], ["credit_card_statements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transaction_id"], ["bank_transactions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_card_payments_card_id"), "credit_card_payments", ["card_id"], unique=False)
    op.create_index(op.f("ix_credit_card_payments_reference"), "credit_card_payments", ["reference"], unique=True)

    # 15. transfer_authorizations
    op.create_table(
        "transfer_authorizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("challenge_hash", sa.String(length=64), nullable=False),
        sa.Column("summary_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["bank_transactions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id"),
    )


def downgrade() -> None:
    op.drop_table("transfer_authorizations")
    op.drop_index(op.f("ix_credit_card_payments_reference"), table_name="credit_card_payments")
    op.drop_index(op.f("ix_credit_card_payments_card_id"), table_name="credit_card_payments")
    op.drop_table("credit_card_payments")
    op.drop_index(op.f("ix_loan_applications_user_id"), table_name="loan_applications")
    op.drop_index(op.f("ix_loan_applications_reference"), table_name="loan_applications")
    op.drop_table("loan_applications")
    op.drop_index(op.f("ix_credit_card_statements_card_id"), table_name="credit_card_statements")
    op.drop_table("credit_card_statements")
    op.drop_index("ix_bank_transactions_user_status", table_name="bank_transactions")
    op.drop_index(op.f("ix_bank_transactions_user_id"), table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_user_created", table_name="bank_transactions")
    op.drop_index(op.f("ix_bank_transactions_reference"), table_name="bank_transactions")
    op.drop_index(op.f("ix_bank_transactions_beneficiary_id"), table_name="bank_transactions")
    op.drop_table("bank_transactions")
    op.drop_table("user_roles")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_revoked_at"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_refresh_token_hash"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_loan_offers_user_id"), table_name="loan_offers")
    op.drop_table("loan_offers")
    op.drop_index(op.f("ix_credit_cards_user_id"), table_name="credit_cards")
    op.drop_table("credit_cards")
    op.drop_index(op.f("ix_beneficiaries_user_id"), table_name="beneficiaries")
    op.drop_table("beneficiaries")
    op.drop_index(op.f("ix_bank_accounts_user_id"), table_name="bank_accounts")
    op.drop_table("bank_accounts")
    op.drop_index(op.f("ix_approval_challenge_user_id"), table_name="approval_challenge")
    op.drop_index(op.f("ix_approval_challenge_approval_token_hash"), table_name="approval_challenge")
    op.drop_table("approval_challenge")
    op.drop_index(op.f("ix_users_phone"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_roles_name"), table_name="roles")
    op.drop_table("roles")
    op.drop_index(op.f("ix_audit_logs_ts"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_user_id"), table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_ts", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action_ts", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
