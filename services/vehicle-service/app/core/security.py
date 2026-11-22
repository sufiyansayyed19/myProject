import hmac
import uuid
from pathlib import Path

import jwt
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.errors import AppError

SERVICE_ROOT = Path(__file__).resolve().parents[2]
bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_key_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (SERVICE_ROOT / path).resolve()


def _load_public_key() -> str:
    return _resolve_key_path(settings.JWT_PUBLIC_KEY_PATH).read_text(encoding="utf-8")


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


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    internal_token: str | None = Header(default=None, alias="X-Internal-Service-Token"),
) -> uuid.UUID:
    # If an internal service token is present (e.g., Parking -> Vehicle), validate it strictly.
    if internal_token is not None:
        if not hmac.compare_digest(internal_token, settings.PARKING_TO_VEHICLE_TOKEN):
            raise AppError(401, "INTERNAL_CALLER_UNAUTHORIZED", "Invalid internal service token.")

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "UNAUTHENTICATED", "Missing or invalid authorization header.")

    return decode_access_token(credentials.credentials)
