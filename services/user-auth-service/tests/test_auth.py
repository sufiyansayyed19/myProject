import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.auth import AuthIdentity, User, VerificationCode  # noqa: E402
from app.services import google_oauth  # noqa: E402
from app.services.email_sender import get_email_sender  # noqa: E402


class CapturingEmailSender:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_verification_code(self, email: str, code: str) -> None:
        self.sent.append((email, code))


@pytest.fixture()
def test_env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, class_=Session, autocommit=False, autoflush=False)

    sender = CapturingEmailSender()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = lambda: sender

    with TestClient(app) as client:
        yield client, TestingSession, sender

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_health(test_env):
    client, _, _ = test_env
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "user-auth-service"}
    assert "X-Request-ID" in r.headers


def test_non_corporate_email_rejected(test_env):
    client, _, sender = test_env
    r = client.post("/api/v1/auth/company/send-code", json={"email": "user@gmail.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CORPORATE_EMAIL_REQUIRED"
    assert len(sender.sent) == 0


def test_otp_full_lifecycle_refresh_and_logout(test_env):
    client, _, sender = test_env

    # 1. Send code
    r1 = client.post("/api/v1/auth/company/send-code", json={"email": "Alice@Company.com"})
    assert r1.status_code == 200
    assert len(sender.sent) == 1
    email, code = sender.sent[0]
    assert email == "alice@company.com"
    assert len(code) == 6

    # 2. Immediate resend blocked by cooldown
    r_cooldown = client.post("/api/v1/auth/company/send-code", json={"email": "alice@company.com"})
    assert r_cooldown.status_code == 429
    assert r_cooldown.json()["error"]["code"] == "OTP_RATE_LIMITED"

    # 3. Wrong OTP rejected
    wrong = "000000" if code != "000000" else "111111"
    r_wrong = client.post("/api/v1/auth/company/verify", json={"email": "alice@company.com", "code": wrong})
    assert r_wrong.status_code == 401
    assert r_wrong.json()["error"]["code"] == "INVALID_OR_EXPIRED_CODE"

    # 4. Correct OTP succeeds, issues JWT + HttpOnly refresh cookie
    r_ok = client.post("/api/v1/auth/company/verify", json={"email": "alice@company.com", "code": code})
    assert r_ok.status_code == 200
    body = r_ok.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "alice@company.com"
    access_token = body["access_token"]
    old_refresh_cookie = r_ok.cookies.get("refresh_token")
    assert old_refresh_cookie

    # 5. Replay same OTP is rejected
    r_replay = client.post("/api/v1/auth/company/verify", json={"email": "alice@company.com", "code": code})
    assert r_replay.status_code == 401

    # 6. GET /api/v1/users/me works with Bearer token
    r_me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert r_me.status_code == 200
    assert r_me.json()["email"] == "alice@company.com"

    # 7. POST /api/v1/auth/refresh rotates refresh cookie & issues new access token
    r_ref = client.post("/api/v1/auth/refresh")
    assert r_ref.status_code == 200
    assert r_ref.json()["access_token"]
    new_refresh_cookie = r_ref.cookies.get("refresh_token")
    assert new_refresh_cookie and new_refresh_cookie != old_refresh_cookie

    # 8. Reusing the old rotated refresh token fails with 401
    r_old = client.post("/api/v1/auth/refresh", cookies={"refresh_token": old_refresh_cookie})
    assert r_old.status_code == 401

    # 9. Logout revokes current refresh cookie (and repeated logout is safe)
    client.cookies.set("refresh_token", new_refresh_cookie, path="/api/v1/auth")
    r_out = client.post("/api/v1/auth/logout")
    assert r_out.status_code == 200
    r_after = client.post("/api/v1/auth/refresh", cookies={"refresh_token": new_refresh_cookie})
    assert r_after.status_code == 401


def test_otp_max_attempts_and_expiry(test_env):
    client, SessionMaker, sender = test_env

    client.post("/api/v1/auth/company/send-code", json={"email": "bob@company.com"})
    _, code = sender.sent[0]
    wrong = "000000" if code != "000000" else "111111"

    for i in range(settings.OTP_MAX_ATTEMPTS - 1):
        r = client.post("/api/v1/auth/company/verify", json={"email": "bob@company.com", "code": wrong})
        assert r.status_code == 401

    # 5th failure exhausts attempts
    r_max = client.post("/api/v1/auth/company/verify", json={"email": "bob@company.com", "code": wrong})
    assert r_max.status_code == 429
    assert r_max.json()["error"]["code"] == "OTP_ATTEMPTS_EXCEEDED"

    # Manually insert an expired code and verify rejection
    with SessionMaker() as db:
        now = datetime.now(timezone.utc)
        db.add(
            VerificationCode(
                email="expired@company.com",
                code_hash="dummy",
                expires_at=now - timedelta(seconds=10),
                attempt_count=0,
                created_at=now - timedelta(minutes=6),
            )
        )
        db.commit()

    r_exp = client.post("/api/v1/auth/company/verify", json={"email": "expired@company.com", "code": "123456"})
    assert r_exp.status_code == 401


def test_google_oauth_verified_account_linking(test_env, monkeypatch):
    client, SessionMaker, sender = test_env

    # First create user via company email OTP
    client.post("/api/v1/auth/company/send-code", json={"email": "carol@company.com"})
    _, code = sender.sent[0]
    r_otp = client.post("/api/v1/auth/company/verify", json={"email": "carol@company.com", "code": code})
    assert r_otp.status_code == 200
    original_user_id = r_otp.json()["user"]["id"]

    # Mock Google OAuth exchange returning verified corporate email
    monkeypatch.setattr(
        google_oauth,
        "exchange_code_for_userinfo",
        lambda _code: google_oauth.GoogleUserInfo(
            subject="google-sub-999",
            email="Carol@Company.com",
            email_verified=True,
            name="Carol Employee",
        ),
    )

    # State mismatch fails with 400
    r_bad_state = client.get(
        "/api/v1/auth/google/callback?code=abc&state=wrong",
        cookies={"oauth_state": "expected"},
        follow_redirects=False,
    )
    assert r_bad_state.status_code == 400
    assert r_bad_state.json()["error"]["code"] == "INVALID_OAUTH_STATE"

    # Valid state links GOOGLE identity to the SAME user record
    r_cb = client.get(
        "/api/v1/auth/google/callback?code=abc&state=expected",
        cookies={"oauth_state": "expected"},
        follow_redirects=False,
    )
    assert r_cb.status_code == 302
    assert r_cb.headers["location"] == settings.FRONTEND_AUTH_SUCCESS_URL
    assert r_cb.cookies.get("refresh_token")

    with SessionMaker() as db:
        users = db.execute(select(User)).scalars().all()
        assert len(users) == 1
        assert str(users[0].id) == original_user_id
        assert users[0].name == "Carol Employee"
        identities = db.execute(select(AuthIdentity)).scalars().all()
        assert {i.provider for i in identities} == {"COMPANY_EMAIL", "GOOGLE"}
