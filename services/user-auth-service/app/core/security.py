import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import jwt
from jwt import InvalidTokenError

from app.core.config import settings
from app.core.errors import APIError

SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _resolve_key_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute() and path.exists():
        return path
    from_service = (SERVICE_ROOT / path).resolve()
    if from_service.exists():
        return from_service
    from_cwd = Path.cwd() / path
    if from_cwd.exists():
        return from_cwd
    # Fallback: check repo root keys/ directory
    from_repo = (SERVICE_ROOT.parents[1] / "keys" / path.name).resolve()
    if from_repo.exists():
        return from_repo
    raise FileNotFoundError(f"RSA key file not found: {raw_path}")


@lru_cache(maxsize=2)
def _load_key_bytes(raw_path: str) -> bytes:
    return _resolve_key_path(raw_path).read_bytes()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_allowed_corporate_email(email: str) -> bool:
    normalized = normalize_email(email)
    allowed_domain = settings.COMPANY_EMAIL_DOMAIN.strip().lower()
    if "@" not in normalized:
        return False
    _, domain = normalized.rsplit("@", 1)
    return domain == allowed_domain


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(email: str, code: str) -> str:
    msg = f"{normalize_email(email)}:{code}".encode("utf-8")
    key = settings.OTP_HMAC_SECRET.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_otp_hash(email: str, code: str, expected_hash: str) -> bool:
    actual_hash = hash_otp(email, code)
    return hmac.compare_digest(actual_hash, expected_hash)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    payload = {
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_seconds)).timestamp()),
    }
    private_key = _load_key_bytes(settings.JWT_PRIVATE_KEY_PATH)
    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token, expires_seconds


def decode_access_token(token: str) -> uuid.UUID:
    try:
        public_key = _load_key_bytes(settings.JWT_PUBLIC_KEY_PATH)
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={"require": ["sub", "iss", "aud", "iat", "exp"]},
        )
        return uuid.UUID(payload["sub"])
    except (InvalidTokenError, ValueError, KeyError) as exc:
        raise APIError(401, "UNAUTHENTICATED", "Invalid or expired access token.") from exc
