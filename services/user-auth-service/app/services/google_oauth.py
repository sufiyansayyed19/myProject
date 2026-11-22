from dataclasses import dataclass
from urllib.parse import urlencode
import httpx

from app.core.config import settings
from app.core.errors import APIError

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass
class GoogleUserInfo:
    subject: str
    email: str
    email_verified: bool
    name: str | None = None


def build_google_authorize_url(state: str) -> str:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise APIError(502, "GOOGLE_PROVIDER_UNAVAILABLE", "Google OAuth is not configured.")
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_userinfo(code: str) -> GoogleUserInfo:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise APIError(502, "GOOGLE_PROVIDER_UNAVAILABLE", "Google OAuth is not configured.")

    try:
        with httpx.Client(timeout=10.0) as client:
            token_resp = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                raise APIError(401, "GOOGLE_AUTHENTICATION_FAILED", "Google token exchange failed.")
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise APIError(401, "GOOGLE_AUTHENTICATION_FAILED", "Missing Google access token.")

            info_resp = client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if info_resp.status_code != 200:
                raise APIError(401, "GOOGLE_AUTHENTICATION_FAILED", "Failed to fetch Google user profile.")
            data = info_resp.json()
    except APIError:
        raise
    except httpx.HTTPError as exc:
        raise APIError(502, "GOOGLE_PROVIDER_UNAVAILABLE", "Unable to reach Google OAuth provider.") from exc

    sub = data.get("sub")
    email = data.get("email")
    if not sub or not email:
        raise APIError(401, "GOOGLE_AUTHENTICATION_FAILED", "Incomplete Google identity claims.")

    return GoogleUserInfo(
        subject=str(sub),
        email=str(email),
        email_verified=bool(data.get("email_verified", False)),
        name=data.get("name"),
    )
