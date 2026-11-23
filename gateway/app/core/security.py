from pathlib import Path
import jwt

from app.core.config import settings

GATEWAY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = GATEWAY_ROOT.parent


def _resolve_public_key_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    candidate = (GATEWAY_ROOT / path).resolve()
    if candidate.exists():
        return candidate
    return (REPO_ROOT / path).resolve()


def validate_access_token(token: str) -> dict:
    public_key = _resolve_public_key_path(settings.JWT_PUBLIC_KEY_PATH).read_text(encoding="utf-8")
    return jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["iss", "aud", "sub", "iat", "exp"]},
    )
