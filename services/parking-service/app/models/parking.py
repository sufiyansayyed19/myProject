import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ParkingSlot(Base):
    __tablename__ = "parking_slots"
    __table_args__ = (
        CheckConstraint("vehicle_type IN ('CAR', 'BIKE')", name="ck_parking_slots_vehicle_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slot_number: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(10), nullable=False)
    is_charging_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="slot")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("vehicle_type_snapshot IN ('CAR', 'BIKE')", name="ck_bookings_vehicle_type_snapshot"),
        CheckConstraint(
            "status IN ('PAYMENT_PENDING', 'CONFIRMED', 'EXPIRED', 'CANCELLED')",
            name="ck_bookings_status",
        ),
        CheckConstraint("end_time > start_time", name="ck_bookings_time_order"),
        CheckConstraint("amount >= 0", name="ck_bookings_amount_non_negative"),
        Index("ix_bookings_user_date", "user_id", "booking_date"),
        Index("ix_bookings_slot_date_status", "slot_id", "booking_date", "status"),
        Index("ix_bookings_hold_expires_at", "hold_expires_at"),
        Index("ix_bookings_vehicle_id", "vehicle_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Immutable vehicle snapshots captured at booking creation (A-41)
    vehicle_number_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    vehicle_type_snapshot: Mapped[str] = mapped_column(String(10), nullable=False)
    is_ev_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)

    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parking_slots.id"), nullable=False
    )
    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    requires_charging: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PAYMENT_PENDING")
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    slot: Mapped["ParkingSlot"] = relationship("ParkingSlot", back_populates="bookings")


class BookingIdempotencyKey(Base):
    __tablename__ = "booking_idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_booking_idempotency_user_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
