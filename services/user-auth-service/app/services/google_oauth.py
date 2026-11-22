from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.errors import AppError

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass
class GoogleUserInfo:
    subject: str
    email: str
    email_verified: bool
    name: str | None


class GoogleOAuthClient:
    def build_authorization_url(self, state: str) -> str:
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_REDIRECT_URI:
            raise AppError(502, "GOOGLE_PROVIDER_UNAVAILABLE", "Google OAuth is not configured.")
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

    def exchange_code_for_userinfo(self, code: str) -> GoogleUserInfo:
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise AppError(502, "GOOGLE_PROVIDER_UNAVAILABLE", "Google OAuth credentials are missing.")
        try:
            with httpx.Client(timeout=5.0) as client:
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
                    raise AppError(401, "GOOGLE_AUTHENTICATION_FAILED", "Failed to exchange Google code.")
                access_token = token_resp.json().get("access_token")
                if not access_token:
                    raise AppError(401, "GOOGLE_AUTHENTICATION_FAILED", "Google token response incomplete.")

                info_resp = client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if info_resp.status_code != 200:
                    raise AppError(401, "GOOGLE_AUTHENTICATION_FAILED", "Failed to fetch Google user profile.")
                data = info_resp.json()
        except AppError:
            raise
        except httpx.HTTPError:
            raise AppError(502, "GOOGLE_PROVIDER_UNAVAILABLE", "Google identity provider is unavailable.")

        subject = data.get("sub")
        email = data.get("email")
        if not subject or not email:
            raise AppError(401, "GOOGLE_AUTHENTICATION_FAILED", "Google profile missing required fields.")

        return GoogleUserInfo(
            subject=str(subject),
            email=str(email),
            email_verified=bool(data.get("email_verified", False)),
            name=data.get("name"),
        )


def get_google_oauth_client() -> GoogleOAuthClient:
    return GoogleOAuthClient()
