import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models.auth import User

SERVICE_ROOT = Path(__file__).resolve().parents[2]
bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_key_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (SERVICE_ROOT / path).resolve()


def _load_private_key() -> str:
    return _resolve_key_path(settings.JWT_PRIVATE_KEY_PATH).read_text(encoding="utf-8")


def _load_public_key() -> str:
    return _resolve_key_path(settings.JWT_PUBLIC_KEY_PATH).read_text(encoding="utf-8")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_allowed_corporate_email(normalized_email: str) -> bool:
    allowed_domain = settings.COMPANY_EMAIL_DOMAIN.strip().lower()
    if "@" not in normalized_email:
        return False
    _, domain = normalized_email.rsplit("@", 1)
    return domain == allowed_domain


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp_code(normalized_email: str, code: str) -> str:
    msg = f"{normalized_email}:{code}".encode("utf-8")
    key = settings.OTP_HMAC_SECRET.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_otp_hash(normalized_email: str, code: str, expected_hash: str) -> bool:
    computed = hash_otp_code(normalized_email, code)
    return hmac.compare_digest(computed, expected_hash)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    payload = {
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, _load_private_key(), algorithm="RS256")
    return token, expires_in


def decode_access_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            _load_public_key(),
            algorithms=["RS256"],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={"require": ["iss", "aud", "sub", "iat", "exp"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise AppError(401, "UNAUTHENTICATED", "Invalid or expired access token.")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "UNAUTHENTICATED", "Missing or invalid authorization header.")

    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if not user:
        raise AppError(401, "UNAUTHENTICATED", "Authenticated user not found.")
    return user
