from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import and_, desc, func, or_, select, text
from sqlalchemy.orm import Session, joinedload

from app.core.clock import as_utc, get_now
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import AuthContext, get_auth_context
from app.models.parking import Booking, BookingIdempotencyKey, ParkingSlot
from app.schemas.parking import (
    AvailabilityResponse,
    BookingCancelResponse,
    BookingCreateRequest,
    BookingListResponse,
    BookingResponse,
)
from app.services.clients import (
    PaymentServiceClient,
    VehicleServiceClient,
    get_payment_client,
    get_vehicle_client,
)
from app.services.rules import (
    calculate_booking_amount,
    calculate_hourly_rate,
    can_cancel_booking,
    validate_booking_interval,
    validate_charging_compatibility,
)

router = APIRouter(prefix="/api/v1/parking", tags=["parking"])

HOLD_DURATION_MINUTES = 5


def _active_booking_filter(now_utc: datetime):
    return or_(
        Booking.status == "CONFIRMED",
        and_(Booking.status == "PAYMENT_PENDING", Booking.hold_expires_at > now_utc),
    )


def _format_time(t: time) -> str:
    return t.strftime("%H:%M")


def _to_booking_response(booking: Booking, slot_number: str) -> BookingResponse:
    return BookingResponse(
        booking_id=booking.id,
        vehicle_id=booking.vehicle_id,
        vehicle_number_snapshot=booking.vehicle_number_snapshot,
        vehicle_type_snapshot=booking.vehicle_type_snapshot,
        is_ev_snapshot=booking.is_ev_snapshot,
        slot_number=slot_number,
        date=booking.booking_date,
        start_time=_format_time(booking.start_time),
        end_time=_format_time(booking.end_time),
        requires_charging=booking.requires_charging,
        amount=booking.amount,
        status=booking.status,
        payment_id=booking.payment_id,
        hold_expires_at=booking.hold_expires_at,
        cancelled_at=booking.cancelled_at,
    )


def _request_payload_hash(payload: BookingCreateRequest) -> str:
    canonical = json.dumps(
        {
            "vehicle_id": str(payload.vehicle_id),
            "date": payload.date.isoformat(),
            "start_time": _format_time(payload.start_time),
            "end_time": _format_time(payload.end_time),
            "requires_charging": payload.requires_charging,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _acquire_user_advisory_lock(db: Session, user_id: uuid.UUID) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(user_id.bytes).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})


def _expire_stale_holds(db: Session, bookings: list[Booking], now_utc: datetime) -> None:
    changed = False
    for b in bookings:
        if b.status == "PAYMENT_PENDING" and b.hold_expires_at is not None and as_utc(b.hold_expires_at) <= now_utc:
            b.status = "EXPIRED"
            changed = True
    if changed:
        db.commit()


@router.get("/availability", response_model=AvailabilityResponse)
def check_availability(
    request: Request,
    booking_date: date = Query(alias="date"),
    start_time: time = Query(...),
    end_time: time = Query(...),
    vehicle_id: uuid.UUID = Query(...),
    requires_charging: bool = Query(...),
    auth: AuthContext = Depends(get_auth_context),
    now: datetime = Depends(get_now),
    db: Session = Depends(get_db),
    vehicle_client: VehicleServiceClient = Depends(get_vehicle_client),
):
    validate_booking_interval(booking_date, start_time, end_time, now)

    request_id = getattr(request.state, "request_id", None)
    vehicle = vehicle_client.get_owned_vehicle(
        vehicle_id=vehicle_id,
        bearer_token=auth.raw_token,
        request_id=request_id,
    )
    validate_charging_compatibility(vehicle.is_ev, requires_charging)

    now_utc = as_utc(now)
    slot_query = select(ParkingSlot.id).where(ParkingSlot.vehicle_type == vehicle.vehicle_type)
    if requires_charging:
        slot_query = slot_query.where(ParkingSlot.is_charging_enabled.is_(True))
    else:
        slot_query = slot_query.where(ParkingSlot.is_charging_enabled.is_(False))
    compatible_slot_ids = list(db.execute(slot_query).scalars().all())

    if not compatible_slot_ids:
        available_count = 0
    else:
        occupied_slot_ids = set(
            db.execute(
                select(Booking.slot_id)
                .where(
                    Booking.slot_id.in_(compatible_slot_ids),
                    Booking.booking_date == booking_date,
                    Booking.start_time < end_time,
                    Booking.end_time > start_time,
                    _active_booking_filter(now_utc),
                )
                .distinct()
            ).scalars().all()
        )
        available_count = len(compatible_slot_ids) - len(occupied_slot_ids)

    return AvailabilityResponse(
        available=available_count > 0,
        available_slots=available_count,
        vehicle_type=vehicle.vehicle_type,
        is_ev=vehicle.is_ev,
        requires_charging=requires_charging,
        rate_per_hour=calculate_hourly_rate(requires_charging),
    )


@router.post("/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: uuid.UUID = Header(..., alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_auth_context),
    now: datetime = Depends(get_now),
    db: Session = Depends(get_db),
    vehicle_client: VehicleServiceClient = Depends(get_vehicle_client),
    payment_client: PaymentServiceClient = Depends(get_payment_client),
):
    req_hash = _request_payload_hash(payload)
    request_id = getattr(request.state, "request_id", None)
    now_utc = as_utc(now)

    # 1. Check existing idempotency record for (user_id, idempotency_key)
    existing_idem = db.execute(
        select(BookingIdempotencyKey).where(
            BookingIdempotencyKey.user_id == auth.user_id,
            BookingIdempotencyKey.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()

    if existing_idem is not None:
        if existing_idem.request_hash != req_hash:
            raise AppError(
                409,
                "IDEMPOTENCY_CONFLICT",
                "Idempotency-Key was already used with a different booking payload.",
            )
        existing_booking = db.execute(
            select(Booking).options(joinedload(Booking.slot)).where(Booking.id == existing_idem.booking_id)
        ).scalar_one()
        _expire_stale_holds(db, [existing_booking], now_utc)
        # Recover payment creation if the previous attempt timed out before saving payment_id
        if (
            existing_booking.payment_id is None
            and existing_booking.status == "PAYMENT_PENDING"
            and existing_booking.hold_expires_at is not None
            and as_utc(existing_booking.hold_expires_at) > now_utc
        ):
            payment_id = payment_client.create_payment(
                booking_id=existing_booking.id,
                user_id=auth.user_id,
                amount=existing_booking.amount,
                expires_at=as_utc(existing_booking.hold_expires_at),
                request_id=request_id,
            )
            existing_booking.payment_id = payment_id
            db.commit()
            db.refresh(existing_booking)

        response.status_code = status.HTTP_200_OK
        return _to_booking_response(existing_booking, existing_booking.slot.slot_number)

    # 2. Validate time rules and vehicle attributes
    validate_booking_interval(payload.date, payload.start_time, payload.end_time, now)
    vehicle = vehicle_client.get_owned_vehicle(
        vehicle_id=payload.vehicle_id,
        bearer_token=auth.raw_token,
        request_id=request_id,
    )
    validate_charging_compatibility(vehicle.is_ev, payload.requires_charging)

    amount = calculate_booking_amount(payload.start_time, payload.end_time, payload.requires_charging)
    hold_expires_at = now_utc + timedelta(minutes=HOLD_DURATION_MINUTES)

    # 3. Transaction: per-user advisory lock + slot row locking + overlap recheck (Q-06, Q-17)
    _acquire_user_advisory_lock(db, auth.user_id)

    user_overlap = db.execute(
        select(Booking.id)
        .where(
            Booking.user_id == auth.user_id,
            Booking.booking_date == payload.date,
            Booking.start_time < payload.end_time,
            Booking.end_time > payload.start_time,
            _active_booking_filter(now_utc),
        )
        .limit(1)
    ).scalar_one_or_none()
    if user_overlap is not None:
        raise AppError(
            409,
            "USER_BOOKING_OVERLAP",
            "You already have an overlapping active booking for this time interval.",
        )

    slot_stmt = (
        select(ParkingSlot)
        .where(
            ParkingSlot.vehicle_type == vehicle.vehicle_type,
            ParkingSlot.is_charging_enabled.is_(payload.requires_charging),
        )
        .order_by(ParkingSlot.slot_number.asc())
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        slot_stmt = slot_stmt.with_for_update()

    compatible_slots = list(db.execute(slot_stmt).scalars().all())
    compatible_slot_ids = [s.id for s in compatible_slots]

    occupied_slot_ids = set()
    if compatible_slot_ids:
        occupied_slot_ids = set(
            db.execute(
                select(Booking.slot_id)
                .where(
                    Booking.slot_id.in_(compatible_slot_ids),
                    Booking.booking_date == payload.date,
                    Booking.start_time < payload.end_time,
                    Booking.end_time > payload.start_time,
                    _active_booking_filter(now_utc),
                )
                .distinct()
            ).scalars().all()
        )

    chosen_slot = next((s for s in compatible_slots if s.id not in occupied_slot_ids), None)
    if chosen_slot is None:
        raise AppError(
            409,
            "NO_PARKING_CAPACITY",
            "No compatible parking slot is available for the requested interval.",
        )

    booking = Booking(
        user_id=auth.user_id,
        vehicle_id=vehicle.id,
        vehicle_number_snapshot=vehicle.vehicle_number,
        vehicle_type_snapshot=vehicle.vehicle_type,
        is_ev_snapshot=vehicle.is_ev,
        slot_id=chosen_slot.id,
        booking_date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        requires_charging=payload.requires_charging,
        status="PAYMENT_PENDING",
        amount=amount,
        hold_expires_at=hold_expires_at,
    )
    db.add(booking)
    db.flush()

    db.add(
        BookingIdempotencyKey(
            user_id=auth.user_id,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            booking_id=booking.id,
        )
    )
    # Commit booking hold BEFORE calling Payment Service (never hold a DB transaction across HTTP)
    db.commit()
    db.refresh(booking)

    # 4. Create payment attempt in Payment Service and persist payment_id
    payment_id = payment_client.create_payment(
        booking_id=booking.id,
        user_id=auth.user_id,
        amount=booking.amount,
        expires_at=hold_expires_at,
        request_id=request_id,
    )
    booking.payment_id = payment_id
    db.commit()
    db.refresh(booking)

    return _to_booking_response(booking, chosen_slot.slot_number)


@router.get("/bookings", response_model=BookingListResponse)
def list_bookings(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_auth_context),
    now: datetime = Depends(get_now),
    db: Session = Depends(get_db),
):
    now_utc = as_utc(now)
    total_items = db.execute(
        select(func.count(Booking.id)).where(Booking.user_id == auth.user_id)
    ).scalar_one()

    rows = list(
        db.execute(
            select(Booking)
            .options(joinedload(Booking.slot))
            .where(Booking.user_id == auth.user_id)
            .order_by(desc(Booking.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    _expire_stale_holds(db, rows, now_utc)

    return BookingListResponse(
        items=[_to_booking_response(b, b.slot.slot_number) for b in rows],
        page=page,
        page_size=page_size,
        total_items=total_items,
    )


@router.get("/bookings/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    now: datetime = Depends(get_now),
    db: Session = Depends(get_db),
):
    booking = db.execute(
        select(Booking)
        .options(joinedload(Booking.slot))
        .where(Booking.id == booking_id, Booking.user_id == auth.user_id)
    ).scalar_one_or_none()
    if booking is None:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found.")

    _expire_stale_holds(db, [booking], as_utc(now))
    return _to_booking_response(booking, booking.slot.slot_number)


@router.post("/bookings/{booking_id}/cancel", response_model=BookingCancelResponse)
def cancel_booking(
    booking_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    now: datetime = Depends(get_now),
    db: Session = Depends(get_db),
):
    stmt = select(Booking).where(Booking.id == booking_id, Booking.user_id == auth.user_id)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()

    booking = db.execute(stmt).scalar_one_or_none()
    if booking is None:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found.")

    now_utc = as_utc(now)
    _expire_stale_holds(db, [booking], now_utc)

    if booking.status != "CONFIRMED":
        raise AppError(
            409,
            "BOOKING_NOT_CANCELLABLE",
            f"Only confirmed bookings can be cancelled (current status: {booking.status}).",
        )

    if not can_cancel_booking(booking.booking_date, booking.start_time, now):
        raise AppError(
            409,
            "BOOKING_NOT_CANCELLABLE",
            "Confirmed bookings can only be cancelled strictly more than 5 minutes before the start time.",
        )

    booking.status = "CANCELLED"
    booking.cancelled_at = now_utc
    db.commit()
    db.refresh(booking)

    return BookingCancelResponse(
        booking_id=booking.id,
        status=booking.status,
        cancelled_at=booking.cancelled_at,
    )
