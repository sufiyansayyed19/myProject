"""initial vehicle tables

Revision ID: 0001_initial_vehicle_tables
Revises:
Create Date: 2026-11-23 01:55:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_vehicle_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_number", sa.String(length=20), nullable=False),
        sa.Column("vehicle_type", sa.String(length=10), nullable=False),
        sa.Column("is_ev", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("vehicle_type IN ('CAR', 'BIKE')", name="ck_vehicles_vehicle_type"),
    )
    op.create_index("ix_vehicles_user_id", "vehicles", ["user_id"], unique=False)
    op.create_index(
        "uq_vehicles_active_user_number",
        "vehicles",
        ["user_id", "vehicle_number"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_vehicles_active_user_number", table_name="vehicles")
    op.drop_index("ix_vehicles_user_id", table_name="vehicles")
    op.drop_table("vehicles")
