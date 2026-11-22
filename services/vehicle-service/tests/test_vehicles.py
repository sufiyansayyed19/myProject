from datetime import datetime, timedelta, timezone
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

from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.main import app  # noqa: E402
from app.services.parking_client import ParkingDependencyClient, get_parking_client  # noqa: E402


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


class FakeParkingClient(ParkingDependencyClient):
    def __init__(self, blocking: bool = False, unavailable: bool = False) -> None:
        self.blocking = blocking
        self.unavailable = unavailable

    def has_blocking_booking(self, vehicle_id: uuid.UUID, request_id: str | None = None) -> bool:
        if self.unavailable:
            raise AppError(503, "PARKING_SERVICE_UNAVAILABLE", "Parking Service is down.")
        return self.blocking


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    parking_client = FakeParkingClient(blocking=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_parking_client] = lambda: parking_client

    client = TestClient(app)
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    yield {
        "client": client,
        "parking_client": parking_client,
        "headers_a": {"Authorization": f"Bearer {_make_jwt(user_a)}"},
        "headers_b": {"Authorization": f"Bearer {_make_jwt(user_b)}"},
    }
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_vehicle_crud_normalization_and_reregistration(ctx):
    client = ctx["client"]
    h_a = ctx["headers_a"]

    # 1. Create with messy formatting -> normalized
    r1 = client.post(
        "/api/v1/vehicles",
        json={"vehicle_number": "mh 12-ab 1234", "vehicle_type": "CAR", "is_ev": True},
        headers=h_a,
    )
    assert r1.status_code == 201
    v1 = r1.json()
    assert v1["vehicle_number"] == "MH12AB1234"
    assert v1["is_active"] is True

    # 2. Duplicate active plate for same user -> 409
    r_dup = client.post(
        "/api/v1/vehicles",
        json={"vehicle_number": "MH12AB1234", "vehicle_type": "CAR", "is_ev": False},
        headers=h_a,
    )
    assert r_dup.status_code == 409
    assert r_dup.json()["error"]["code"] == "VEHICLE_ALREADY_REGISTERED"

    # 3. List returns active vehicles
    r_list = client.get("/api/v1/vehicles", headers=h_a)
    assert r_list.status_code == 200
    assert len(r_list.json()["vehicles"]) == 1

    # 4. Update vehicle (no blocking booking)
    r_upd = client.put(
        f"/api/v1/vehicles/{v1['id']}",
        json={"vehicle_number": "MH12 AB 9999", "vehicle_type": "CAR", "is_ev": False},
        headers=h_a,
    )
    assert r_upd.status_code == 200
    assert r_upd.json()["vehicle_number"] == "MH12AB9999"
    assert r_upd.json()["is_ev"] is False

    # 5. Soft deactivate
    r_del = client.delete(f"/api/v1/vehicles/{v1['id']}", headers=h_a)
    assert r_del.status_code == 200
    assert r_del.json()["is_active"] is False

    # 6. Inactive vehicle hidden from GET and list
    assert client.get(f"/api/v1/vehicles/{v1['id']}", headers=h_a).status_code == 404
    assert client.get("/api/v1/vehicles", headers=h_a).json()["vehicles"] == []

    # 7. Re-registering deactivated plate creates a new active row (Q-21)
    r_re = client.post(
        "/api/v1/vehicles",
        json={"vehicle_number": "MH12AB9999", "vehicle_type": "CAR", "is_ev": True},
        headers=h_a,
    )
    assert r_re.status_code == 201
    assert r_re.json()["id"] != v1["id"]


def test_owner_isolation_and_internal_token_validation(ctx):
    client = ctx["client"]
    h_a = ctx["headers_a"]
    h_b = ctx["headers_b"]

    v = client.post(
        "/api/v1/vehicles",
        json={"vehicle_number": "KA01CD5678", "vehicle_type": "BIKE", "is_ev": False},
        headers=h_a,
    ).json()

    # User B cannot view, update, or delete User A's vehicle (404 non-disclosing)
    assert client.get(f"/api/v1/vehicles/{v['id']}", headers=h_b).status_code == 404
    assert client.delete(f"/api/v1/vehicles/{v['id']}", headers=h_b).status_code == 404

    # Valid Parking -> Vehicle internal token + user JWT succeeds
    r_internal_ok = client.get(
        f"/api/v1/vehicles/{v['id']}",
        headers={**h_a, "X-Internal-Service-Token": settings.PARKING_TO_VEHICLE_TOKEN},
    )
    assert r_internal_ok.status_code == 200

    # Wrong internal token rejected with 401
    r_internal_bad = client.get(
        f"/api/v1/vehicles/{v['id']}",
        headers={**h_a, "X-Internal-Service-Token": "wrong-token"},
    )
    assert r_internal_bad.status_code == 401
    assert r_internal_bad.json()["error"]["code"] == "INTERNAL_CALLER_UNAUTHORIZED"


def test_blocking_booking_and_fail_closed_behavior(ctx):
    client = ctx["client"]
    h_a = ctx["headers_a"]

    v = client.post(
        "/api/v1/vehicles",
        json={"vehicle_number": "DL05XY1111", "vehicle_type": "CAR", "is_ev": True},
        headers=h_a,
    ).json()

    # Blocking booking prevents update and deactivation (409)
    ctx["parking_client"].blocking = True
    r_upd = client.put(
        f"/api/v1/vehicles/{v['id']}",
        json={"vehicle_number": "DL05XY1111", "vehicle_type": "CAR", "is_ev": False},
        headers=h_a,
    )
    assert r_upd.status_code == 409
    assert r_upd.json()["error"]["code"] == "VEHICLE_HAS_BLOCKING_BOOKING"

    r_del = client.delete(f"/api/v1/vehicles/{v['id']}", headers=h_a)
    assert r_del.status_code == 409

    # Parking Service unavailable fails closed (503)
    ctx["parking_client"].blocking = False
    ctx["parking_client"].unavailable = True
    r_down = client.delete(f"/api/v1/vehicles/{v['id']}", headers=h_a)
    assert r_down.status_code == 503
    assert r_down.json()["error"]["code"] == "PARKING_SERVICE_UNAVAILABLE"


def test_invalid_vehicle_type_rejected(ctx):
    r = ctx["client"].post(
        "/api/v1/vehicles",
        json={"vehicle_number": "MH12AB1234", "vehicle_type": "TRUCK", "is_ev": False},
        headers=ctx["headers_a"],
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_VEHICLE_DATA"
