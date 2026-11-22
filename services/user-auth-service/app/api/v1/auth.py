import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Cookie, Depends, Header, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import APIError
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_otp_code,
    generate_refresh_token,
    hash_otp,
    hash_refresh_token,
    is_allowed_corporate_email,
    normalize_email,
    verify_otp_hash,
)
from app.models.auth import AuthIdentity, RefreshSession, User, VerificationCode
from app.schemas.auth import (
    AuthTokenResponse,
    MessageResponse,
    RefreshTokenResponse,
    SendCodeRequest,
    UserResponse,
    VerifyCodeRequest,
)
from app.services.email_sender import EmailSender, get_email_sender
from app.services import google_oauth

router = APIRouter(prefix="/api/v1", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
OAUTH_STATE_COOKIE_NAME = "oauth_state"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_secure_cookie() -> bool:
    return settings.ENVIRONMENT.lower() == "production"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=_is_secure_cookie(),
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/v1/auth")


def _issue_session_and_tokens(db: Session, user: User, response: Response) -> tuple[str, int]:
    now = _utcnow()
    raw_refresh = generate_refresh_token()
    session_row = RefreshSession(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        created_at=now,
    )
    db.add(session_row)
    db.commit()

    access_token, expires_in = create_access_token(user.id)
    _set_refresh_cookie(response, raw_refresh)
    return access_token, expires_in


def get_current_user_id(authorization: str | None = Header(default=None)) -> uuid.UUID:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise APIError(401, "UNAUTHENTICATED", "Missing or invalid authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise APIError(401, "UNAUTHENTICATED", "Missing access token.")
    return decode_access_token(token)


# 1. POST /api/v1/auth/company/send-code
@router.post("/auth/company/send-code", response_model=MessageResponse)
def send_company_code(
    payload: SendCodeRequest,
    db: Session = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
):
    email = normalize_email(payload.email)
    if not is_allowed_corporate_email(email):
        raise APIError(403, "CORPORATE_EMAIL_REQUIRED", "Only corporate email addresses are allowed.")

    now = _utcnow()
    latest = db.execute(
        select(VerificationCode)
        .where(VerificationCode.email == email)
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if latest is not None:
        elapsed = (now - _as_utc(latest.created_at)).total_seconds()
        if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
            raise APIError(429, "OTP_RATE_LIMITED", "Please wait before requesting a new verification code.")

    # Invalidate any previous active codes in the same transaction
    active_codes = db.execute(
        select(VerificationCode).where(
            VerificationCode.email == email,
            VerificationCode.consumed_at.is_(None),
            VerificationCode.invalidated_at.is_(None),
        )
    ).scalars().all()
    for old_code in active_codes:
        old_code.invalidated_at = now

    otp_code = generate_otp_code()
    record = VerificationCode(
        email=email,
        code_hash=hash_otp(email, otp_code),
        expires_at=now + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
        attempt_count=0,
        created_at=now,
    )
    db.add(record)
    db.commit()

    try:
        email_sender.send_verification_code(email, otp_code)
    except Exception as exc:
        raise APIError(502, "EMAIL_DELIVERY_FAILED", "Failed to deliver verification code.") from exc

    return MessageResponse(message="Verification code sent successfully")


# 2. POST /api/v1/auth/company/verify
@router.post("/auth/company/verify", response_model=AuthTokenResponse)
def verify_company_code(
    payload: VerifyCodeRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    email = normalize_email(payload.email)
    if not is_allowed_corporate_email(email):
        raise APIError(403, "CORPORATE_EMAIL_REQUIRED", "Only corporate email addresses are allowed.")

    now = _utcnow()
    record = db.execute(
        select(VerificationCode)
        .where(
            VerificationCode.email == email,
            VerificationCode.consumed_at.is_(None),
            VerificationCode.invalidated_at.is_(None),
        )
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if record is None or _as_utc(record.expires_at) <= now:
        raise APIError(401, "INVALID_OR_EXPIRED_CODE", "Verification code is invalid or expired.")

    if record.attempt_count >= settings.OTP_MAX_ATTEMPTS:
        record.invalidated_at = now
        db.commit()
        raise APIError(429, "OTP_ATTEMPTS_EXCEEDED", "Maximum verification attempts exceeded.")

    if not verify_otp_hash(email, payload.code, record.code_hash):
        record.attempt_count += 1
        if record.attempt_count >= settings.OTP_MAX_ATTEMPTS:
            record.invalidated_at = now
            db.commit()
            raise APIError(429, "OTP_ATTEMPTS_EXCEEDED", "Maximum verification attempts exceeded.")
        db.commit()
        raise APIError(401, "INVALID_OR_EXPIRED_CODE", "Verification code is invalid or expired.")

    # Mark code consumed so it cannot be replayed
    record.consumed_at = now

    # Resolve or create user + COMPANY_EMAIL identity
    identity = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == "COMPANY_EMAIL",
            AuthIdentity.provider_subject == email,
        )
    ).scalar_one_or_none()

    if identity is not None:
        user = db.get(User, identity.user_id)
    else:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(email=email, name=None, created_at=now, updated_at=now)
            db.add(user)
            db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider="COMPANY_EMAIL",
                provider_subject=email,
                provider_email=email,
                created_at=now,
            )
        )

    access_token, expires_in = _issue_session_and_tokens(db, user, response)
    return AuthTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


# 3. GET /api/v1/auth/google
@router.get("/auth/google")
def start_google_oauth():
    state = secrets.token_urlsafe(32)
    url = google_oauth.build_google_authorize_url(state)
    redirect = RedirectResponse(url=url, status_code=302)
    redirect.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=_is_secure_cookie(),
        samesite="lax",
        max_age=300,
        path="/api/v1/auth/google",
    )
    return redirect


# 4. GET /api/v1/auth/google/callback
@router.get("/auth/google/callback")
def google_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    oauth_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if not code or not state or not oauth_state or not secrets.compare_digest(state, oauth_state):
        raise APIError(400, "INVALID_OAUTH_STATE", "Invalid or missing OAuth state.")

    info = google_oauth.exchange_code_for_userinfo(code)
    if not info.email_verified:
        raise APIError(401, "GOOGLE_AUTHENTICATION_FAILED", "Google email must be verified.")

    normalized_email = normalize_email(info.email)
    if not is_allowed_corporate_email(normalized_email):
        raise APIError(403, "CORPORATE_GOOGLE_ACCOUNT_REQUIRED", "Google account must use the corporate email domain.")

    now = _utcnow()
    identity = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == "GOOGLE",
            AuthIdentity.provider_subject == info.subject,
        )
    ).scalar_one_or_none()

    if identity is not None:
        user = db.get(User, identity.user_id)
    else:
        # Automatic verified account linking: match verified corporate email
        user = db.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
        if user is None:
            user = User(email=normalized_email, name=info.name, created_at=now, updated_at=now)
            db.add(user)
            db.flush()
        elif not user.name and info.name:
            user.name = info.name
            user.updated_at = now

        db.add(
            AuthIdentity(
                user_id=user.id,
                provider="GOOGLE",
                provider_subject=info.subject,
                provider_email=normalized_email,
                created_at=now,
            )
        )

    redirect = RedirectResponse(url=settings.FRONTEND_AUTH_SUCCESS_URL, status_code=302)
    redirect.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/api/v1/auth/google")
    _issue_session_and_tokens(db, user, redirect)
    return redirect


# 5. GET /api/v1/users/me
@router.get("/users/me", response_model=UserResponse)
def get_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise APIError(401, "UNAUTHENTICATED", "User account not found.")
    return UserResponse.model_validate(user)


# 6. POST /api/v1/auth/refresh
@router.post("/auth/refresh", response_model=RefreshTokenResponse)
def refresh_access_token(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if not refresh_token:
        raise APIError(401, "INVALID_REFRESH_TOKEN", "Missing refresh token.")

    now = _utcnow()
    token_hash = hash_refresh_token(refresh_token)
    session_row = db.execute(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash)
    ).scalar_one_or_none()

    if session_row is None or session_row.revoked_at is not None or _as_utc(session_row.expires_at) <= now:
        _clear_refresh_cookie(response)
        raise APIError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid, expired, or revoked.")

    user = db.get(User, session_row.user_id)
    if user is None:
        _clear_refresh_cookie(response)
        raise APIError(401, "INVALID_REFRESH_TOKEN", "User account not found.")

    # Rotate refresh token: revoke old session and issue new one
    session_row.revoked_at = now
    access_token, expires_in = _issue_session_and_tokens(db, user, response)
    return RefreshTokenResponse(access_token=access_token, expires_in=expires_in)


# 7. POST /api/v1/auth/logout
@router.post("/auth/logout", response_model=MessageResponse)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        session_row = db.execute(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        ).scalar_one_or_none()
        if session_row is not None and session_row.revoked_at is None:
            session_row.revoked_at = _utcnow()
            db.commit()

    _clear_refresh_cookie(response)
    return MessageResponse(message="Logged out successfully")
