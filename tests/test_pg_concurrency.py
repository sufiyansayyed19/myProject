"""Real PostgreSQL concurrency & locking tests against parking_db (Q-06, Section 8)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import threading
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

REPO_ROOT = Path(__file__).resolve().parents[1]
PARKING_DIR = REPO_ROOT / "services" / "parking-service"
if str(PARKING_DIR) not in sys.path:
    sys.path.insert(0, str(PARKING_DIR))

from app.core.clock import IST_FALLBACK, get_now  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.parking import Booking, BookingIdempotencyKey, ParkingSlot  # noqa: E402
from app.services.clients import (  # noqa: E402
    PaymentServiceClient,
    VehicleInfo,
    VehicleServiceClient,
    get_payment_client,
    get_vehicle_client,
)


def _make_jwt(user_id: uuid.UUID) -> str:
    private_key = (REPO_ROOT / "keys" / "jwt_private.pem").read_text(encoding="utf-8")
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


class _StubVehicleClient(VehicleServiceClient):
    def __init__(self, vehicle_type: str, is_ev: bool) -> None:
        self.vehicle_type = vehicle_type
        self.is_ev = is_ev

    def get_owned_vehicle(self, vehicle_id: uuid.UUID, bearer_token: str, request_id: str | None = None) -> VehicleInfo:
        return VehicleInfo(
            id=vehicle_id,
            vehicle_number=f"RACE{vehicle_id.hex[:6].upper()}",
            vehicle_type=self.vehicle_type,
            is_ev=self.is_ev,
            is_active=True,
        )


class _StubPaymentClient(PaymentServiceClient):
    def create_payment(
        self,
        booking_id: uuid.UUID,
        user_id: uuid.UUID,
        amount: Decimal,
        expires_at: datetime,
        request_id: str | None = None,
    ) -> uuid.UUID:
        return uuid.uuid4()


def _cleanup_bookings(user_ids: list[uuid.UUID]) -> None:
    with SessionLocal() as db:
        db.execute(delete(BookingIdempotencyKey).where(BookingIdempotencyKey.user_id.in_(user_ids)))
        db.execute(delete(Booking).where(Booking.user_id.in_(user_ids)))
        db.commit()


def test_pg_ev_bike_slot_race_no_double_allocation():
    """10 different users simultaneously race for the 5 EV-charging bike slots (B36-B40)."""
    # Monday 2026-11-23 08:30 IST
    fixed_now = datetime(2026, 11, 23, 8, 30, 0, tzinfo=IST_FALLBACK)
    target_date = "2026-11-23"

    user_ids = [uuid.uuid4() for _ in range(10)]
    app.dependency_overrides[get_now] = lambda: fixed_now
    app.dependency_overrides[get_vehicle_client] = lambda: _StubVehicleClient("BIKE", True)
    app.dependency_overrides[get_payment_client] = lambda: _StubPaymentClient()

    barrier = threading.Barrier(len(user_ids))

    def book_for_user(uid: uuid.UUID):
        client = TestClient(app)
        barrier.wait()
        resp = client.post(
            "/api/v1/parking/bookings",
            json={
                "vehicle_id": str(uuid.uuid4()),
                "date": target_date,
                "start_time": "10:00",
                "end_time": "11:00",
                "requires_charging": True,
            },
            headers={
                "Authorization": f"Bearer {_make_jwt(uid)}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )
        return resp.status_code, resp.json()

    try:
        with ThreadPoolExecutor(max_workers=len(user_ids)) as pool:
            results = list(pool.map(book_for_user, user_ids))

        successes = [body for code, body in results if code == 201]
        conflicts = [body for code, body in results if code == 409]

        # Exactly 5 EV-bike slots exist in parking_db (B36-B40)
        assert len(successes) == 5, f"Expected 5 successes, got {len(successes)}: {results}"
        assert len(conflicts) == 5
        allocated_slots = [b["slot_number"] for b in successes]
        assert len(set(allocated_slots)) == 5, f"Duplicate slot allocated! {allocated_slots}"
        assert all(c["error"]["code"] == "NO_PARKING_CAPACITY" for c in conflicts)
    finally:
        app.dependency_overrides.clear()
        _cleanup_bookings(user_ids)


def test_pg_same_user_simultaneous_overlap_serialized():
    """1 user fires 4 simultaneous overlapping requests with different vehicles -> at most 1 succeeds."""
    fixed_now = datetime(2026, 11, 23, 8, 30, 0, tzinfo=IST_FALLBACK)
    user_id = uuid.uuid4()

    app.dependency_overrides[get_now] = lambda: fixed_now
    app.dependency_overrides[get_vehicle_client] = lambda: _StubVehicleClient("CAR", False)
    app.dependency_overrides[get_payment_client] = lambda: _StubPaymentClient()

    barrier = threading.Barrier(4)
    token = _make_jwt(user_id)

    def attempt(_idx: int):
        client = TestClient(app)
        barrier.wait()
        resp = client.post(
            "/api/v1/parking/bookings",
            json={
                "vehicle_id": str(uuid.uuid4()),
                "date": "2026-11-23",
                "start_time": "14:00",
                "end_time": "16:00",
                "requires_charging": False,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )
        return resp.status_code, resp.json()

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))

        successes = [body for code, body in results if code == 201]
        overlaps = [body for code, body in results if code == 409]

        assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}: {results}"
        assert len(overlaps) == 3
        assert all(o["error"]["code"] == "USER_BOOKING_OVERLAP" for o in overlaps)
    finally:
        app.dependency_overrides.clear()
        _cleanup_bookings([user_id])
