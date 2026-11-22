"""initial parking tables and 100 sample slots

Revision ID: 0001_initial_parking_tables
Revises:
Create Date: 2026-11-23 02:10:00
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_parking_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _build_seed_slots() -> list[dict]:
    slots: list[dict] = []
    # 60 car spaces: C01-C50 normal, C51-C60 charging-enabled
    for i in range(1, 61):
        slots.append(
            {
                "id": uuid.uuid4(),
                "slot_number": f"C{i:02d}",
                "vehicle_type": "CAR",
                "is_charging_enabled": i > 50,
            }
        )
    # 40 bike spaces: B01-B35 normal, B36-B40 charging-enabled
    for i in range(1, 41):
        slots.append(
            {
                "id": uuid.uuid4(),
                "slot_number": f"B{i:02d}",
                "vehicle_type": "BIKE",
                "is_charging_enabled": i > 35,
            }
        )
    return slots


def upgrade() -> None:
    parking_slots_table = op.create_table(
        "parking_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slot_number", sa.String(length=10), nullable=False),
        sa.Column("vehicle_type", sa.String(length=10), nullable=False),
        sa.Column("is_charging_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("slot_number", name="uq_parking_slots_slot_number"),
        sa.CheckConstraint("vehicle_type IN ('CAR', 'BIKE')", name="ck_parking_slots_vehicle_type"),
    )

    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_number_snapshot", sa.String(length=20), nullable=False),
        sa.Column("vehicle_type_snapshot", sa.String(length=10), nullable=False),
        sa.Column("is_ev_snapshot", sa.Boolean(), nullable=False),
        sa.Column("slot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("parking_slots.id"), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(timezone=False), nullable=False),
        sa.Column("end_time", sa.Time(timezone=False), nullable=False),
        sa.Column("requires_charging", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("payment_id", name="uq_bookings_payment_id"),
        sa.CheckConstraint("vehicle_type_snapshot IN ('CAR', 'BIKE')", name="ck_bookings_vehicle_type_snapshot"),
        sa.CheckConstraint(
            "status IN ('PAYMENT_PENDING', 'CONFIRMED', 'EXPIRED', 'CANCELLED')",
            name="ck_bookings_status",
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_bookings_time_order"),
        sa.CheckConstraint("amount >= 0", name="ck_bookings_amount_non_negative"),
    )
    op.create_index("ix_bookings_user_date", "bookings", ["user_id", "booking_date"], unique=False)
    op.create_index("ix_bookings_slot_date_status", "bookings", ["slot_id", "booking_date", "status"], unique=False)
    op.create_index("ix_bookings_hold_expires_at", "bookings", ["hold_expires_at"], unique=False)
    op.create_index("ix_bookings_vehicle_id", "bookings", ["vehicle_id"], unique=False)

    op.create_table(
        "booking_idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "booking_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_booking_idempotency_user_key"),
    )

    op.bulk_insert(parking_slots_table, _build_seed_slots())


def downgrade() -> None:
    op.drop_table("booking_idempotency_keys")
    op.drop_index("ix_bookings_vehicle_id", table_name="bookings")
    op.drop_index("ix_bookings_hold_expires_at", table_name="bookings")
    op.drop_index("ix_bookings_slot_date_status", table_name="bookings")
    op.drop_index("ix_bookings_user_date", table_name="bookings")
    op.drop_table("bookings")
    op.drop_table("parking_slots")
