import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Numeric, String, Text, desc
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("callback_attempts >= 0", name="ck_payments_callback_attempts_non_negative"),
        CheckConstraint("status IN ('PENDING', 'SUCCESS', 'FAILED')", name="ck_payments_status"),
        CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('UPI', 'CARD', 'WALLET')",
            name="ck_payments_method",
        ),
        Index("ix_payments_user_created_at", "user_id", desc("created_at")),
        Index("ix_payments_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    callback_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    callback_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_callback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    callback_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
