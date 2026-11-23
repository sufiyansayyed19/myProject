from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.core.clock import IST_FALLBACK, as_utc, get_now  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.parking import Booking, ParkingSlot  # noqa: E402


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    clock = {"now": datetime(2026, 11, 23, 9, 0, 0, tzinfo=IST_FALLBACK)}

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_now] = lambda: clock["now"]

    with TestingSessionLocal() as db:
        slot = ParkingSlot(slot_number="C01", vehicle_type="CAR", is_charging_enabled=False)
        db.add(slot)
        db.commit()
        slot_id = slot.id

    yield {
        "client": TestClient(app),
        "db_factory": TestingSessionLocal,
        "clock": clock,
        "slot_id": slot_id,
        "pay_headers": {"X-Internal-Service-Token": settings.PAYMENT_TO_PARKING_TOKEN},
        "veh_headers": {"X-Internal-Service-Token": settings.VEHICLE_TO_PARKING_TOKEN},
    }
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_payment_result_callback_confirm_duplicate_and_late_no_resurrection(ctx):
    client = ctx["client"]
    now_utc = as_utc(ctx["clock"]["now"])
    payment_id = uuid.uuid4()

    with ctx["db_factory"]() as db:
        b = Booking(
            user_id=uuid.uuid4(),
            vehicle_id=uuid.uuid4(),
            vehicle_number_snapshot="MH12AB1234",
            vehicle_type_snapshot="CAR",
            is_ev_snapshot=False,
            slot_id=ctx["slot_id"],
            booking_date=date(2026, 11, 23),
            start_time=time(11, 0),
            end_time=time(12, 0),
            requires_charging=False,
            status="PAYMENT_PENDING",
            amount=Decimal("10.00"),
            hold_expires_at=now_utc + timedelta(minutes=5),
            payment_id=payment_id,
        )
        db.add(b)
        db.commit()
        booking_id = b.id

    # Missing internal token -> 401
    cb_body = {
        "payment_id": str(payment_id),
        "status": "SUCCESS",
        "transaction_id": "TXN123",
        "processed_at": now_utc.isoformat(),
    }
    assert client.post(f"/internal/v1/bookings/{booking_id}/payment-result", json=cb_body).status_code == 401

    # Valid SUCCESS within hold -> CONFIRMED
    r1 = client.post(
        f"/internal/v1/bookings/{booking_id}/payment-result",
        json=cb_body,
        headers=ctx["pay_headers"],
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "CONFIRMED"
    assert r1.json()["result"] == "APPLIED"

    # Duplicate identical SUCCESS callback -> idempotent ALREADY_APPLIED
    r2 = client.post(
        f"/internal/v1/bookings/{booking_id}/payment-result",
        json=cb_body,
        headers=ctx["pay_headers"],
    )
    assert r2.status_code == 200
    assert r2.json()["result"] == "ALREADY_APPLIED"

    # Late SUCCESS after hold expiry -> EXPIRED, NEVER resurrected (A-23)
    p2_id = uuid.uuid4()
    with ctx["db_factory"]() as db:
        b2 = Booking(
            user_id=uuid.uuid4(),
            vehicle_id=uuid.uuid4(),
            vehicle_number_snapshot="MH12AB1234",
            vehicle_type_snapshot="CAR",
            is_ev_snapshot=False,
            slot_id=ctx["slot_id"],
            booking_date=date(2026, 11, 23),
            start_time=time(14, 0),
            end_time=time(15, 0),
            requires_charging=False,
            status="PAYMENT_PENDING",
            amount=Decimal("10.00"),
            hold_expires_at=now_utc - timedelta(seconds=10),
            payment_id=p2_id,
        )
        db.add(b2)
        db.commit()
        b2_id = b2.id

    r_late = client.post(
        f"/internal/v1/bookings/{b2_id}/payment-result",
        json={
            "payment_id": str(p2_id),
            "status": "SUCCESS",
            "transaction_id": "TXNLATE",
            "processed_at": now_utc.isoformat(),
        },
        headers=ctx["pay_headers"],
    )
    assert r_late.status_code == 200
    assert r_late.json()["status"] == "EXPIRED"


def test_vehicle_booking_dependency_check(ctx):
    client = ctx["client"]
    vehicle_id = uuid.uuid4()
    now_utc = as_utc(ctx["clock"]["now"])

    # No bookings -> not blocking
    r0 = client.get(f"/internal/v1/vehicles/{vehicle_id}/booking-dependency", headers=ctx["veh_headers"])
    assert r0.status_code == 200
    assert r0.json()["has_blocking_booking"] is False

    # Add an already-ended CONFIRMED booking (07:00-08:00 when now is 09:00) & a CANCELLED booking -> still not blocking
    with ctx["db_factory"]() as db:
        db.add_all(
            [
                Booking(
                    user_id=uuid.uuid4(),
                    vehicle_id=vehicle_id,
                    vehicle_number_snapshot="MH12AB1234",
                    vehicle_type_snapshot="CAR",
                    is_ev_snapshot=False,
                    slot_id=ctx["slot_id"],
                    booking_date=date(2026, 11, 23),
                    start_time=time(7, 0),
                    end_time=time(8, 0),
                    requires_charging=False,
                    status="CONFIRMED",
                    amount=Decimal("10.00"),
                ),
                Booking(
                    user_id=uuid.uuid4(),
                    vehicle_id=vehicle_id,
                    vehicle_number_snapshot="MH12AB1234",
                    vehicle_type_snapshot="CAR",
                    is_ev_snapshot=False,
                    slot_id=ctx["slot_id"],
                    booking_date=date(2026, 11, 23),
                    start_time=time(15, 0),
                    end_time=time(16, 0),
                    requires_charging=False,
                    status="CANCELLED",
                    amount=Decimal("10.00"),
                ),
            ]
        )
        db.commit()

    r1 = client.get(f"/internal/v1/vehicles/{vehicle_id}/booking-dependency", headers=ctx["veh_headers"])
    assert r1.json()["has_blocking_booking"] is False

    # Add a future CONFIRMED booking -> blocking!
    with ctx["db_factory"]() as db:
        db.add(
            Booking(
                user_id=uuid.uuid4(),
                vehicle_id=vehicle_id,
                vehicle_number_snapshot="MH12AB1234",
                vehicle_type_snapshot="CAR",
                is_ev_snapshot=False,
                slot_id=ctx["slot_id"],
                booking_date=date(2026, 11, 23),
                start_time=time(11, 0),
                end_time=time(12, 0),
                requires_charging=False,
                status="CONFIRMED",
                amount=Decimal("10.00"),
                hold_expires_at=now_utc + timedelta(minutes=5),
            )
        )
        db.commit()

    r2 = client.get(f"/internal/v1/vehicles/{vehicle_id}/booking-dependency", headers=ctx["veh_headers"])
    assert r2.status_code == 200
    assert r2.json()["has_blocking_booking"] is True
    assert r2.json()["blocking_booking_count"] == 1
