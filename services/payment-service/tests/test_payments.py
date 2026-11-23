from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.api.v1.payments import get_now_utc  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.parking_callback import ParkingCallbackClient, get_callback_client  # noqa: E402


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


class CapturingCallbackClient(ParkingCallbackClient):
    def __init__(self) -> None:
        self.deliveries: list[dict] = []

    def deliver_payment_result(
        self,
        booking_id: uuid.UUID,
        payment_id: uuid.UUID,
        status: str,
        transaction_id: str | None,
        processed_at: datetime,
        request_id: str | None = None,
    ) -> tuple[bool, int, str | None]:
        self.deliveries.append({"booking_id": booking_id, "payment_id": payment_id, "status": status})
        return True, 1, None


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    clock = {"now": datetime(2026, 11, 23, 9, 0, 0, tzinfo=timezone.utc)}
    cb_client = CapturingCallbackClient()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_now_utc] = lambda: clock["now"]
    app.dependency_overrides[get_callback_client] = lambda: cb_client

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    yield {
        "client": TestClient(app),
        "clock": clock,
        "cb_client": cb_client,
        "user_a": user_a,
        "headers_a": {"Authorization": f"Bearer {_make_jwt(user_a)}"},
        "headers_b": {"Authorization": f"Bearer {_make_jwt(user_b)}"},
        "internal_headers": {"X-Internal-Service-Token": settings.PARKING_TO_PAYMENT_TOKEN},
    }
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_internal_payment_create_idempotency_and_auth(ctx):
    client = ctx["client"]
    booking_id = str(uuid.uuid4())
    payload = {
        "booking_id": booking_id,
        "user_id": str(ctx["user_a"]),
        "amount": 60.00,
        "expires_at": (ctx["clock"]["now"] + timedelta(minutes=5)).isoformat(),
    }

    # Missing internal token -> 401
    assert client.post("/internal/v1/payments", json=payload).status_code == 401

    # Valid internal create -> 201
    r1 = client.post("/internal/v1/payments", json=payload, headers=ctx["internal_headers"])
    assert r1.status_code == 201
    p1 = r1.json()
    assert p1["status"] == "PENDING"

    # Idempotent replay with same values -> 200 same payment_id
    r2 = client.post("/internal/v1/payments", json=payload, headers=ctx["internal_headers"])
    assert r2.status_code == 200
    assert r2.json()["payment_id"] == p1["payment_id"]

    # Conflicting amount for same booking -> 409
    r_conflict = client.post(
        "/internal/v1/payments",
        json={**payload, "amount": 99.00},
        headers=ctx["internal_headers"],
    )
    assert r_conflict.status_code == 409
    assert r_conflict.json()["error"]["code"] == "PAYMENT_REQUEST_CONFLICT"


def test_process_success_failure_override_ownership_and_expiry(ctx):
    client = ctx["client"]
    expires = ctx["clock"]["now"] + timedelta(minutes=5)

    # Create payment 1 (default SUCCESS)
    p1 = client.post(
        "/internal/v1/payments",
        json={"booking_id": str(uuid.uuid4()), "user_id": str(ctx["user_a"]), "amount": 40.00, "expires_at": expires.isoformat()},
        headers=ctx["internal_headers"],
    ).json()

    # User B cannot access or process User A's payment (404)
    assert client.get(f"/api/v1/payments/{p1['payment_id']}", headers=ctx["headers_b"]).status_code == 404
    assert (
        client.post(
            f"/api/v1/payments/{p1['payment_id']}/process",
            json={"payment_method": "UPI"},
            headers=ctx["headers_b"],
        ).status_code
        == 404
    )

    # Process payment 1 -> SUCCESS + transaction_id + callback delivered
    r_ok = client.post(
        f"/api/v1/payments/{p1['payment_id']}/process",
        json={"payment_method": "UPI"},
        headers=ctx["headers_a"],
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "SUCCESS"
    assert r_ok.json()["transaction_id"].startswith("TXN")
    assert len(ctx["cb_client"].deliveries) == 1

    # Repeated process -> 409 PAYMENT_ALREADY_PROCESSED
    r_dup = client.post(
        f"/api/v1/payments/{p1['payment_id']}/process",
        json={"payment_method": "CARD"},
        headers=ctx["headers_a"],
    )
    assert r_dup.status_code == 409
    assert r_dup.json()["error"]["code"] == "PAYMENT_ALREADY_PROCESSED"

    # Payment 2 with deterministic X-Test-Payment-Outcome: FAILED override
    p2 = client.post(
        "/internal/v1/payments",
        json={"booking_id": str(uuid.uuid4()), "user_id": str(ctx["user_a"]), "amount": 20.00, "expires_at": expires.isoformat()},
        headers=ctx["internal_headers"],
    ).json()
    r_fail = client.post(
        f"/api/v1/payments/{p2['payment_id']}/process",
        json={"payment_method": "WALLET"},
        headers={**ctx["headers_a"], "X-Test-Payment-Outcome": "FAILED"},
    )
    assert r_fail.status_code == 200
    assert r_fail.json()["status"] == "FAILED"
    assert r_fail.json()["transaction_id"] is None

    # Payment 3 after expiry -> 409 PAYMENT_EXPIRED
    p3 = client.post(
        "/internal/v1/payments",
        json={"booking_id": str(uuid.uuid4()), "user_id": str(ctx["user_a"]), "amount": 20.00, "expires_at": expires.isoformat()},
        headers=ctx["internal_headers"],
    ).json()
    ctx["clock"]["now"] = expires + timedelta(seconds=1)
    r_exp = client.post(
        f"/api/v1/payments/{p3['payment_id']}/process",
        json={"payment_method": "CARD"},
        headers=ctx["headers_a"],
    )
    assert r_exp.status_code == 409
    assert r_exp.json()["error"]["code"] == "PAYMENT_EXPIRED"
