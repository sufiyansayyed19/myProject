from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.auth import AuthIdentity, User, VerificationCode  # noqa: E402
from app.services.email_sender import EmailSender, get_email_sender  # noqa: E402
from app.services.google_oauth import GoogleOAuthClient, GoogleUserInfo, get_google_oauth_client  # noqa: E402


class CapturingEmailSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_otp(self, email: str, code: str, expires_minutes: int) -> None:
        self.sent.append((email, code))


class FakeGoogleOAuthClient(GoogleOAuthClient):
    def __init__(self, user_info: GoogleUserInfo | None = None) -> None:
        self.user_info = user_info or GoogleUserInfo(
            subject="google-sub-123",
            email="alice@company.com",
            email_verified=True,
            name="Alice Employee",
        )

    def build_authorization_url(self, state: str) -> str:
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"

    def exchange_code_for_userinfo(self, code: str) -> GoogleUserInfo:
        return self.user_info


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    email_sender = CapturingEmailSender()
    google_client = FakeGoogleOAuthClient()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    app.dependency_overrides[get_google_oauth_client] = lambda: google_client

    client = TestClient(app)
    yield {
        "client": client,
        "db_factory": TestingSessionLocal,
        "email_sender": email_sender,
        "google_client": google_client,
    }
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_health_and_request_id(ctx):
    resp = ctx["client"].get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "user-auth-service"
    assert "X-Request-ID" in resp.headers


def test_reject_non_corporate_email(ctx):
    resp = ctx["client"].post("/api/v1/auth/company/send-code", json={"email": "outsider@gmail.com"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CORPORATE_EMAIL_REQUIRED"


def test_company_otp_full_flow_refresh_and_logout(ctx):
    client = ctx["client"]
    sender = ctx["email_sender"]

    # 1. Send OTP
    r1 = client.post("/api/v1/auth/company/send-code", json={"email": "Alice@Company.com"})
    assert r1.status_code == 200
    assert len(sender.sent) == 1
    sent_email, otp_code = sender.sent[0]
    assert sent_email == "alice@company.com"
    assert otp_code not in r1.text

    # 2. Immediate resend hits cooldown
    r_cooldown = client.post("/api/v1/auth/company/send-code", json={"email": "alice@company.com"})
    assert r_cooldown.status_code == 429
    assert r_cooldown.json()["error"]["code"] == "OTP_RATE_LIMITED"

    # 3. Wrong OTP increments attempts
    r_bad = client.post("/api/v1/auth/company/verify", json={"email": "alice@company.com", "code": "000000"})
    assert r_bad.status_code == 401
    assert r_bad.json()["error"]["code"] == "INVALID_OR_EXPIRED_CODE"

    # 4. Correct OTP authenticates and sets HttpOnly refresh cookie
    r_ok = client.post("/api/v1/auth/company/verify", json={"email": "alice@company.com", "code": otp_code})
    assert r_ok.status_code == 200
    body = r_ok.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "alice@company.com"
    access_token = body["access_token"]
    old_refresh = r_ok.cookies.get("refresh_token")
    assert old_refresh is not None

    # 5. Replaying same OTP fails
    r_replay = client.post("/api/v1/auth/company/verify", json={"email": "alice@company.com", "code": otp_code})
    assert r_replay.status_code == 401

    # 6. /users/me succeeds with RS256 Bearer token
    r_me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert r_me.status_code == 200
    assert r_me.json()["email"] == "alice@company.com"

    # 7. Refresh rotates cookie and returns new access token
    r_ref = client.post("/api/v1/auth/refresh")
    assert r_ref.status_code == 200
    new_refresh = r_ref.cookies.get("refresh_token")
    assert new_refresh and new_refresh != old_refresh

    # 8. Reusing the old (rotated) refresh token is rejected
    client.cookies.set("refresh_token", old_refresh)
    r_old_ref = client.post("/api/v1/auth/refresh")
    assert r_old_ref.status_code == 401

    # 9. Logout revokes active refresh session
    client.cookies.set("refresh_token", new_refresh)
    r_out = client.post("/api/v1/auth/logout")
    assert r_out.status_code == 200

    # 10. Refresh after logout is rejected
    client.cookies.set("refresh_token", new_refresh)
    r_after_out = client.post("/api/v1/auth/refresh")
    assert r_after_out.status_code == 401


def test_otp_max_attempts_exhaustion(ctx):
    client = ctx["client"]
    client.post("/api/v1/auth/company/send-code", json={"email": "bob@company.com"})

    for i in range(settings.OTP_MAX_ATTEMPTS - 1):
        r = client.post("/api/v1/auth/company/verify", json={"email": "bob@company.com", "code": "999999"})
        assert r.status_code == 401

    r_last = client.post("/api/v1/auth/company/verify", json={"email": "bob@company.com", "code": "999999"})
    assert r_last.status_code == 429
    assert r_last.json()["error"]["code"] == "OTP_ATTEMPTS_EXCEEDED"


def test_google_oauth_state_validation_and_automatic_account_linking(ctx):
    client = ctx["client"]
    sender = ctx["email_sender"]

    # First login via company email OTP to create user alice@company.com
    client.post("/api/v1/auth/company/send-code", json={"email": "alice@company.com"})
    _, otp = sender.sent[-1]
    r_verify = client.post("/api/v1/auth/company/verify", json={"email": "alice@company.com", "code": otp})
    assert r_verify.status_code == 200
    original_user_id = r_verify.json()["user"]["id"]

    # Start Google OAuth
    r_start = client.get("/api/v1/auth/google", follow_redirects=False)
    assert r_start.status_code == 302
    state_cookie = r_start.cookies.get("oauth_state")
    assert state_cookie

    # State mismatch rejected
    r_bad_state = client.get(
        "/api/v1/auth/google/callback?code=abc&state=wrong-state",
        follow_redirects=False,
    )
    assert r_bad_state.status_code == 400
    assert r_bad_state.json()["error"]["code"] == "INVALID_OAUTH_STATE"

    # Valid Google callback links to the SAME user record (no duplicate user)
    r_cb = client.get(
        f"/api/v1/auth/google/callback?code=valid-code&state={state_cookie}",
        follow_redirects=False,
    )
    assert r_cb.status_code == 302
    assert r_cb.headers["location"] == settings.FRONTEND_AUTH_SUCCESS_URL
    assert r_cb.cookies.get("refresh_token") is not None

    with ctx["db_factory"]() as db:
        users = db.execute(select(User)).scalars().all()
        identities = db.execute(select(AuthIdentity)).scalars().all()
        assert len(users) == 1
        assert str(users[0].id) == original_user_id
        assert users[0].name == "Alice Employee"
        assert {ident.provider for ident in identities} == {"COMPANY_EMAIL", "GOOGLE"}


def test_google_oauth_rejects_unverified_or_non_corporate(ctx):
    client = ctx["client"]
    ctx["google_client"].user_info = GoogleUserInfo(
        subject="google-sub-999",
        email="alice@company.com",
        email_verified=False,
        name="Unverified",
    )
    r_start = client.get("/api/v1/auth/google", follow_redirects=False)
    state_cookie = r_start.cookies.get("oauth_state")

    r_cb = client.get(
        f"/api/v1/auth/google/callback?code=abc&state={state_cookie}",
        follow_redirects=False,
    )
    assert r_cb.status_code == 403
    assert r_cb.json()["error"]["code"] == "CORPORATE_GOOGLE_ACCOUNT_REQUIRED"
