import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    generate_otp_code,
    generate_refresh_token,
    get_current_user,
    hash_otp_code,
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
    UserProfile,
    VerifyCodeRequest,
)
from app.services.email_sender import EmailSender, get_email_sender
from app.services.google_oauth import GoogleOAuthClient, get_google_oauth_client

router = APIRouter(prefix="/api/v1", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
OAUTH_STATE_COOKIE_NAME = "oauth_state"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_cookie_secure() -> bool:
    return settings.ENVIRONMENT.strip().lower() == "production"


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=_is_cookie_secure(),
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",
    )


def _create_refresh_session(db: Session, user: User) -> str:
    raw_token = generate_refresh_token()
    session = RefreshSession(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=_utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    return raw_token


@router.post("/auth/company/send-code", response_model=MessageResponse)
def send_company_code(
    payload: SendCodeRequest,
    db: Session = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
):
    email = normalize_email(str(payload.email))
    if not is_allowed_corporate_email(email):
        raise AppError(403, "CORPORATE_EMAIL_REQUIRED", "Only corporate email addresses are allowed.")

    now = _utcnow()
    latest = db.execute(
        select(VerificationCode)
        .where(VerificationCode.email == email)
        .order_by(desc(VerificationCode.created_at))
        .limit(1)
    ).scalar_one_or_none()

    if latest is not None:
        elapsed = (now - _as_utc(latest.created_at)).total_seconds()
        if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
            raise AppError(429, "OTP_RATE_LIMITED", "Please wait before requesting another verification code.")

    # Invalidate any previously active codes for this email in the same transaction
    active_codes = db.execute(
        select(VerificationCode).where(
            VerificationCode.email == email,
            VerificationCode.consumed_at.is_(None),
            VerificationCode.invalidated_at.is_(None),
        )
    ).scalars().all()
    for code_row in active_codes:
        code_row.invalidated_at = now

    raw_code = generate_otp_code()
    verification = VerificationCode(
        email=email,
        code_hash=hash_otp_code(email, raw_code),
        expires_at=now + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
        attempt_count=0,
    )
    db.add(verification)
    db.commit()

    try:
        email_sender.send_otp(email=email, code=raw_code, expires_minutes=settings.OTP_EXPIRE_MINUTES)
    except Exception:
        raise AppError(502, "EMAIL_DELIVERY_FAILED", "Unable to deliver verification code.")

    return MessageResponse(message="Verification code sent successfully")


@router.post("/auth/company/verify", response_model=AuthTokenResponse)
def verify_company_code(
    payload: VerifyCodeRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    email = normalize_email(str(payload.email))
    now = _utcnow()

    verification = db.execute(
        select(VerificationCode)
        .where(
            VerificationCode.email == email,
            VerificationCode.consumed_at.is_(None),
            VerificationCode.invalidated_at.is_(None),
        )
        .order_by(desc(VerificationCode.created_at))
        .limit(1)
    ).scalar_one_or_none()

    if verification is None or _as_utc(verification.expires_at) <= now:
        raise AppError(401, "INVALID_OR_EXPIRED_CODE", "Verification code is invalid or has expired.")

    if not verify_otp_hash(email, payload.code, verification.code_hash):
        verification.attempt_count += 1
        if verification.attempt_count >= settings.OTP_MAX_ATTEMPTS:
            verification.invalidated_at = now
            db.commit()
            raise AppError(429, "OTP_ATTEMPTS_EXCEEDED", "Maximum verification attempts exceeded.")
        db.commit()
        raise AppError(401, "INVALID_OR_EXPIRED_CODE", "Verification code is invalid or has expired.")

    verification.consumed_at = now

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
            user = User(email=email, name=None)
            db.add(user)
            db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider="COMPANY_EMAIL",
                provider_subject=email,
                provider_email=email,
            )
        )

    raw_refresh = _create_refresh_session(db, user)
    db.commit()
    db.refresh(user)

    access_token, expires_in = create_access_token(user.id)
    _set_refresh_cookie(response, raw_refresh)

    return AuthTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=UserProfile.model_validate(user),
    )


@router.get("/auth/google")
def start_google_oauth(
    google_client: GoogleOAuthClient = Depends(get_google_oauth_client),
):
    state = secrets.token_urlsafe(32)
    auth_url = google_client.build_authorization_url(state=state)
    redirect = RedirectResponse(url=auth_url, status_code=302)
    redirect.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=_is_cookie_secure(),
        samesite="lax",
        max_age=300,
        path="/api/v1/auth/google",
    )
    return redirect


@router.get("/auth/google/callback")
def google_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    oauth_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    db: Session = Depends(get_db),
    google_client: GoogleOAuthClient = Depends(get_google_oauth_client),
):
    if error:
        raise AppError(401, "GOOGLE_AUTHENTICATION_FAILED", "Google authentication was cancelled or failed.")

    if not code or not state or not oauth_state or not hmac.compare_digest(state, oauth_state):
        raise AppError(400, "INVALID_OAUTH_STATE", "Invalid or missing OAuth state.")

    google_info = google_client.exchange_code_for_userinfo(code)
    normalized_email = normalize_email(google_info.email)

    if not google_info.email_verified or not is_allowed_corporate_email(normalized_email):
        raise AppError(
            403,
            "CORPORATE_GOOGLE_ACCOUNT_REQUIRED",
            "A verified corporate Google account is required.",
        )

    identity = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == "GOOGLE",
            AuthIdentity.provider_subject == google_info.subject,
        )
    ).scalar_one_or_none()

    if identity is not None:
        user = db.get(User, identity.user_id)
        if user and not user.name and google_info.name:
            user.name = google_info.name[:100]
    else:
        # Automatic account linking on verified corporate email match (A-42)
        user = db.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
        if user is None:
            user = User(email=normalized_email, name=google_info.name[:100] if google_info.name else None)
            db.add(user)
            db.flush()
        elif not user.name and google_info.name:
            user.name = google_info.name[:100]

        db.add(
            AuthIdentity(
                user_id=user.id,
                provider="GOOGLE",
                provider_subject=google_info.subject,
                provider_email=normalized_email,
            )
        )

    raw_refresh = _create_refresh_session(db, user)
    db.commit()

    redirect = RedirectResponse(url=settings.FRONTEND_AUTH_SUCCESS_URL, status_code=302)
    _set_refresh_cookie(redirect, raw_refresh)
    redirect.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/api/v1/auth/google")
    return redirect


@router.get("/users/me", response_model=UserProfile)
def get_me(current_user: User = Depends(get_current_user)):
    return UserProfile.model_validate(current_user)


@router.post("/auth/refresh", response_model=RefreshTokenResponse)
def refresh_access_token(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if not refresh_token:
        raise AppError(401, "UNAUTHENTICATED", "Missing refresh session.")

    now = _utcnow()
    token_hash = hash_refresh_token(refresh_token)
    session = db.execute(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash)
    ).scalar_one_or_none()

    if session is None or session.revoked_at is not None or _as_utc(session.expires_at) <= now:
        raise AppError(401, "UNAUTHENTICATED", "Refresh session is invalid, revoked, or expired.")

    user = db.get(User, session.user_id)
    if user is None:
        raise AppError(401, "UNAUTHENTICATED", "User not found.")

    # Rotate refresh token
    session.revoked_at = now
    new_raw_refresh = _create_refresh_session(db, user)
    db.commit()

    access_token, expires_in = create_access_token(user.id)
    _set_refresh_cookie(response, new_raw_refresh)

    return RefreshTokenResponse(access_token=access_token, expires_in=expires_in)


@router.post("/auth/logout", response_model=MessageResponse)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        session = db.execute(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        ).scalar_one_or_none()
        if session is not None and session.revoked_at is None:
            session.revoked_at = _utcnow()
            db.commit()

    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/v1/auth")
    return MessageResponse(message="Logged out successfully")
