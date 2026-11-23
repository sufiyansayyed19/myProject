from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import uuid

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

GATEWAY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = GATEWAY_DIR.parent
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402


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


@pytest.fixture()
def captured():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/v1/auth/company/verify":
            return httpx.Response(
                200,
                json={"access_token": "tok", "token_type": "bearer", "expires_in": 900},
                headers={
                    "Set-Cookie": "refresh_token=abc123; HttpOnly; Path=/api/v1/auth",
                },
            )
        if request.url.path == "/api/v1/parking/down":
            raise httpx.ConnectError("connection refused")
        return httpx.Response(
            200,
            json={"forwarded_to": str(request.url), "received_headers": dict(request.headers)},
        )

    transport = httpx.MockTransport(handler)
    original_factory = app.state.http_client_factory
    app.state.http_client_factory = lambda: httpx.AsyncClient(transport=transport, follow_redirects=False)

    yield {"client": TestClient(app), "calls": calls}
    app.state.http_client_factory = original_factory


def test_health_and_internal_routes_blocked(captured):
    client = captured["client"]

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["service"] == "api-gateway"

    # /internal/v1/* must NEVER be exposed or forwarded
    r_int = client.post("/internal/v1/payments", json={})
    assert r_int.status_code == 404
    assert r_int.json()["error"]["code"] == "NOT_FOUND"
    assert len(captured["calls"]) == 0


def test_protected_routes_require_valid_jwt_and_strip_internal_token(captured):
    client = captured["client"]

    # Missing JWT on protected routes -> 401 at Gateway (never reaches downstream)
    assert client.get("/api/v1/vehicles").status_code == 401
    assert client.get("/api/v1/parking/bookings").status_code == 401
    assert client.get("/api/v1/payments/123").status_code == 401
    assert client.get("/api/v1/users/me").status_code == 401
    assert len(captured["calls"]) == 0

    # Valid JWT forwards to vehicle-service AND strips client-supplied X-Internal-Service-Token
    token = _make_jwt(uuid.uuid4())
    r_ok = client.get(
        "/api/v1/vehicles?active=true",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Internal-Service-Token": "spoofed-secret",
        },
    )
    assert r_ok.status_code == 200
    assert len(captured["calls"]) == 1
    forwarded_req = captured["calls"][0]
    assert str(forwarded_req.url).startswith(settings.VEHICLE_SERVICE_URL)
    assert "x-internal-service-token" not in {k.lower() for k in forwarded_req.headers.keys()}
    assert "x-request-id" in {k.lower() for k in forwarded_req.headers.keys()}


def test_public_auth_routes_preserve_cookies_and_503_on_down(captured):
    client = captured["client"]

    # Public /api/v1/auth/company/verify forwards without JWT and preserves Set-Cookie
    r_verify = client.post(
        "/api/v1/auth/company/verify",
        json={"email": "alice@company.com", "code": "123456"},
    )
    assert r_verify.status_code == 200
    assert "refresh_token=abc123" in r_verify.headers.get("set-cookie", "")

    # Downstream failure returns 503 in standard error envelope
    token = _make_jwt(uuid.uuid4())
    r_down = client.get("/api/v1/parking/down", headers={"Authorization": f"Bearer {token}"})
    assert r_down.status_code == 503
    assert r_down.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
