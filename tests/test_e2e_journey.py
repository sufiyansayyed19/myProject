"""Full End-to-End Multi-Service Journey Test across API Gateway + all 4 microservices + 4 PostgreSQL DBs."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

import httpx
import jwt
import pytest
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = str(REPO_ROOT / ".venv" / "Scripts" / "python.exe")
UVICORN_EXE = str(REPO_ROOT / ".venv" / "Scripts" / "uvicorn.exe")

PORTS = {
    "gateway": 18000,
    "auth": 18001,
    "vehicle": 18002,
    "parking": 18003,
    "payment": 18004,
}


def _wait_for_health(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Service did not become healthy at {url}")


def _next_operating_date_iso() -> str:
    # Pick tomorrow in IST, or today if tomorrow is Sunday (and we're early); simplest:
    # if tomorrow is Sunday, pick today (Saturday); otherwise pick tomorrow (always valid for 10:00-12:00).
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)
    tomorrow = now_ist.date() + timedelta(days=1)
    if tomorrow.weekday() == 6:  # Sunday
        # Tomorrow is Sunday -> use today at 20:00-21:00 if before 19:30, else skip
        return now_ist.date().isoformat()
    return tomorrow.isoformat()


def _make_jwt(user_id: uuid.UUID) -> str:
    private_key = (REPO_ROOT / "keys" / "jwt_private.pem").read_text(encoding="utf-8")
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "corporate-parking-auth",
        "aud": "corporate-parking",
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture(scope="module")
def live_stack():
    base_env = os.environ.copy()
    base_env.update(
        {
            "USER_AUTH_SERVICE_URL": f"http://127.0.0.1:{PORTS['auth']}",
            "VEHICLE_SERVICE_URL": f"http://127.0.0.1:{PORTS['vehicle']}",
            "PARKING_SERVICE_URL": f"http://127.0.0.1:{PORTS['parking']}",
            "PAYMENT_SERVICE_URL": f"http://127.0.0.1:{PORTS['payment']}",
            "COMPANY_EMAIL_DOMAIN": "company.com",
            "PAYMENT_SIMULATION_DEFAULT_OUTCOME": "SUCCESS",
            "ENABLE_TEST_PAYMENT_OVERRIDE": "true",
            "ENVIRONMENT": "development",
        }
    )

    specs = [
        ("auth", REPO_ROOT / "services" / "user-auth-service", PORTS["auth"]),
        ("vehicle", REPO_ROOT / "services" / "vehicle-service", PORTS["vehicle"]),
        ("parking", REPO_ROOT / "services" / "parking-service", PORTS["parking"]),
        ("payment", REPO_ROOT / "services" / "payment-service", PORTS["payment"]),
        ("gateway", REPO_ROOT / "gateway", PORTS["gateway"]),
    ]

    procs: list[subprocess.Popen] = []
    try:
        for _name, cwd, port in specs:
            p = subprocess.Popen(
                [UVICORN_EXE, "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(cwd),
                env=base_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            procs.append(p)

        for _name, _cwd, port in specs:
            _wait_for_health(f"http://127.0.0.1:{port}/health")

        yield f"http://127.0.0.1:{PORTS['gateway']}"
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


def _cleanup_e2e_user(user_id: uuid.UUID) -> None:
    uid_str = str(user_id)
    dbs = [
        ("postgresql+psycopg://payment_user:payment_pass@localhost:5432/payment_db", "DELETE FROM payments WHERE user_id = :uid"),
        ("postgresql+psycopg://parking_user:parking_pass@localhost:5432/parking_db", "DELETE FROM booking_idempotency_keys WHERE user_id = :uid"),
        ("postgresql+psycopg://parking_user:parking_pass@localhost:5432/parking_db", "DELETE FROM bookings WHERE user_id = :uid"),
        ("postgresql+psycopg://vehicle_user:vehicle_pass@localhost:5432/vehicle_db", "DELETE FROM vehicles WHERE user_id = :uid"),
    ]
    for url, sql in dbs:
        eng = create_engine(url)
        with eng.begin() as conn:
            conn.execute(text(sql), {"uid": uid_str})
        eng.dispose()


def test_full_e2e_corporate_parking_journey_via_gateway(live_stack):
    gw = live_stack
    user_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_make_jwt(user_id)}"}
    booking_date = _next_operating_date_iso()

    try:
        with httpx.Client(base_url=gw, timeout=10.0) as client:
            # 1. Gateway blocks /internal/v1/*
            assert client.post("/internal/v1/payments", json={}).status_code == 404

            # 2. Register an EV car via Gateway -> Vehicle Service
            r_veh = client.post(
                "/api/v1/vehicles",
                json={"vehicle_number": f"E2E {user_id.hex[:6]}", "vehicle_type": "CAR", "is_ev": True},
                headers=headers,
            )
            assert r_veh.status_code == 201, r_veh.text
            vehicle_id = r_veh.json()["id"]

            # 3. Check availability via Gateway -> Parking Service -> Vehicle Service
            r_avail = client.get(
                "/api/v1/parking/availability",
                params={
                    "date": booking_date,
                    "start_time": "10:00",
                    "end_time": "12:00",
                    "vehicle_id": vehicle_id,
                    "requires_charging": "true",
                },
                headers=headers,
            )
            assert r_avail.status_code == 200, r_avail.text
            assert r_avail.json()["available"] is True
            assert float(r_avail.json()["rate_per_hour"]) == 20.0

            # 4. Create booking via Gateway -> Parking -> Vehicle + Payment (2h * ₹20 = ₹40)
            idem_key = str(uuid.uuid4())
            r_book = client.post(
                "/api/v1/parking/bookings",
                json={
                    "vehicle_id": vehicle_id,
                    "date": booking_date,
                    "start_time": "10:00",
                    "end_time": "12:00",
                    "requires_charging": True,
                },
                headers={**headers, "Idempotency-Key": idem_key},
            )
            assert r_book.status_code == 201, r_book.text
            booking = r_book.json()
            booking_id = booking["booking_id"]
            payment_id = booking["payment_id"]
            assert booking["status"] == "PAYMENT_PENDING"
            assert float(booking["amount"]) == 40.0
            assert payment_id is not None

            # 5. Vehicle deactivation is BLOCKED (409) while active PAYMENT_PENDING hold exists
            r_del_blocked = client.delete(f"/api/v1/vehicles/{vehicle_id}", headers=headers)
            assert r_del_blocked.status_code == 409, r_del_blocked.text
            assert r_del_blocked.json()["error"]["code"] == "VEHICLE_HAS_BLOCKING_BOOKING"

            # 6. Process simulated payment via Gateway -> Payment Service -> callback to Parking
            r_pay = client.post(
                f"/api/v1/payments/{payment_id}/process",
                json={"payment_method": "UPI"},
                headers=headers,
            )
            assert r_pay.status_code == 200, r_pay.text
            assert r_pay.json()["status"] == "SUCCESS"
            assert r_pay.json()["transaction_id"].startswith("TXN")

            # 7. Booking is now CONFIRMED in Parking Service
            r_get_booking = client.get(f"/api/v1/parking/bookings/{booking_id}", headers=headers)
            assert r_get_booking.status_code == 200, r_get_booking.text
            assert r_get_booking.json()["status"] == "CONFIRMED"

            # 8. Vehicle deactivation is STILL BLOCKED (409) while future CONFIRMED booking exists
            assert client.delete(f"/api/v1/vehicles/{vehicle_id}", headers=headers).status_code == 409

            # 9. Cancel the confirmed booking (> 5 min before start)
            r_cancel = client.post(f"/api/v1/parking/bookings/{booking_id}/cancel", headers=headers)
            assert r_cancel.status_code == 200, r_cancel.text
            assert r_cancel.json()["status"] == "CANCELLED"

            # 10. Now vehicle deactivation SUCCEEDS (200) because booking is CANCELLED!
            r_del_ok = client.delete(f"/api/v1/vehicles/{vehicle_id}", headers=headers)
            assert r_del_ok.status_code == 200, r_del_ok.text
            assert r_del_ok.json()["is_active"] is False
    finally:
        _cleanup_e2e_user(user_id)
