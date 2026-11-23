from datetime import datetime
import hmac
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.clock import as_utc, get_business_tz, get_now
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models.parking import Booking

router = APIRouter(prefix="/internal/v1", tags=["internal"])


def _require_payment_service(
    token: str | None = Header(default=None, alias="X-Internal-Service-Token"),
) -> None:
    if not token or not hmac.compare_digest(token, settings.PAYMENT_TO_PARKING_TOKEN):
        raise AppError(401, "INTERNAL_CALLER_UNAUTHORIZED", "Invalid internal service token.")


def _require_vehicle_service(
    token: str | None = Header(default=None, alias="X-Internal-Service-Token"),
) -> None:
    if not token or not hmac.compare_digest(token, settings.VEHICLE_TO_PARKING_TOKEN):
        raise AppError(401, "INTERNAL_CALLER_UNAUTHORIZED", "Invalid internal service token.")


class PaymentResultRequest(BaseModel):
    payment_id: uuid.UUID
    status: Literal["SUCCESS", "FAILED"]
    transaction_id: str | None = None
    processed_at: datetime


class PaymentResultResponse(BaseModel):
    booking_id: uuid.UUID
    status: str
    result: str


class VehicleDependencyResponse(BaseModel):
    has_blocking_booking: bool
    blocking_booking_count: int


@router.post(
    "/bookings/{booking_id}/payment-result",
    response_model=PaymentResultResponse,
    dependencies=[Depends(_require_payment_service)],
)
def apply_payment_result(
    booking_id: uuid.UUID,
    payload: PaymentResultRequest,
    now: datetime = Depends(get_now),
    db: Session = Depends(get_db),
):
    stmt = select(Booking).where(Booking.id == booking_id)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()

    booking = db.execute(stmt).scalar_one_or_none()
    if booking is None:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found.")

    if booking.payment_id is not None and booking.payment_id != payload.payment_id:
        raise AppError(409, "PAYMENT_REFERENCE_MISMATCH", "Callback payment_id does not match booking.")

    now_utc = as_utc(now)

    # Idempotent / terminal state handling
    if booking.status == "CONFIRMED":
        if payload.status == "SUCCESS":
            return PaymentResultResponse(booking_id=booking.id, status="CONFIRMED", result="ALREADY_APPLIED")
        raise AppError(409, "INVALID_BOOKING_TRANSITION", "Cannot apply FAILED callback to a CONFIRMED booking.")

    if booking.status == "EXPIRED":
        if payload.status == "FAILED":
            return PaymentResultResponse(booking_id=booking.id, status="EXPIRED", result="ALREADY_APPLIED")
        # Late SUCCESS must NEVER resurrect an expired booking (A-23)
        return PaymentResultResponse(booking_id=booking.id, status="EXPIRED", result="EXPIRED_NO_RESURRECTION")

    if booking.status == "CANCELLED":
        raise AppError(409, "INVALID_BOOKING_TRANSITION", "Cannot apply payment callback to a CANCELLED booking.")

    # Booking is currently PAYMENT_PENDING
    if booking.payment_id is None:
        booking.payment_id = payload.payment_id

    hold_expired = booking.hold_expires_at is None or as_utc(booking.hold_expires_at) <= now_utc
    if hold_expired or payload.status == "FAILED":
        booking.status = "EXPIRED"
    else:
        booking.status = "CONFIRMED"

    db.commit()
    db.refresh(booking)
    return PaymentResultResponse(booking_id=booking.id, status=booking.status, result="APPLIED")


@router.get(
    "/vehicles/{vehicle_id}/booking-dependency",
    response_model=VehicleDependencyResponse,
    dependencies=[Depends(_require_vehicle_service)],
)
def check_vehicle_booking_dependency(
    vehicle_id: uuid.UUID,
    now: datetime = Depends(get_now),
    db: Session = Depends(get_db),
):
    now_local = now.astimezone(get_business_tz())
    today = now_local.date()
    current_time = now_local.time().replace(tzinfo=None)
    now_utc = as_utc(now)

    blocking_bookings = db.execute(
        select(Booking.id).where(
            Booking.vehicle_id == vehicle_id,
            or_(
                and_(
                    Booking.status == "CONFIRMED",
                    or_(
                        Booking.booking_date > today,
                        and_(Booking.booking_date == today, Booking.end_time > current_time),
                    ),
                ),
                and_(
                    Booking.status == "PAYMENT_PENDING",
                    Booking.hold_expires_at > now_utc,
                ),
            ),
        )
    ).scalars().all()

    count = len(blocking_bookings)
    return VehicleDependencyResponse(
        has_blocking_booking=count > 0,
        blocking_booking_count=count,
    )
