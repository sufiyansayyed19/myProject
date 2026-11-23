"""initial payment tables

Revision ID: 0001_initial_payment_tables
Revises:
Create Date: 2026-11-23 02:16:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_payment_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("payment_method", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("transaction_id", sa.String(length=100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("callback_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callback_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_callback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callback_last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("booking_id", name="uq_payments_booking_id"),
        sa.UniqueConstraint("transaction_id", name="uq_payments_transaction_id"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint("callback_attempts >= 0", name="ck_payments_callback_attempts_non_negative"),
        sa.CheckConstraint("status IN ('PENDING', 'SUCCESS', 'FAILED')", name="ck_payments_status"),
        sa.CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('UPI', 'CARD', 'WALLET')",
            name="ck_payments_method",
        ),
    )
    op.create_index(
        "ix_payments_user_created_at",
        "payments",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index("ix_payments_expires_at", "payments", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payments_expires_at", table_name="payments")
    op.drop_index("ix_payments_user_created_at", table_name="payments")
    op.drop_table("payments")
