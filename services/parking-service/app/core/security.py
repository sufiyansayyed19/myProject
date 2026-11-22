from dataclasses import dataclass
from pathlib import Path
import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.errors import AppError

SERVICE_ROOT = Path(__file__).resolve().parents[2]
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user_id: uuid.UUID
    raw_token: str


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


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "UNAUTHENTICATED", "Missing or invalid authorization header.")

    user_id = decode_access_token(credentials.credentials)
    return AuthContext(user_id=user_id, raw_token=credentials.credentials)
