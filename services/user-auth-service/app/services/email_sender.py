from typing import Protocol
from app.core.config import settings


class EmailSender(Protocol):
    def send_verification_code(self, email: str, code: str) -> None: ...


class ConsoleEmailSender:
    """Local development sender. Never logs OTPs when ENVIRONMENT=production."""

    def send_verification_code(self, email: str, code: str) -> None:
        if settings.ENVIRONMENT.lower() == "production":
            raise RuntimeError("ConsoleEmailSender must not be used in production.")
        print(f"[DEV EMAIL] Verification code for {email}: {code} (valid {settings.OTP_EXPIRE_MINUTES} min)")


def get_email_sender() -> EmailSender:
    # Future: inspect settings.EMAIL_SENDER_MODE to return an SMTP/provider implementation
    return ConsoleEmailSender()
