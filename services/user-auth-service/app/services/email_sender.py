from abc import ABC, abstractmethod
from app.core.config import settings


class EmailSender(ABC):
    @abstractmethod
    def send_otp(self, email: str, code: str, expires_minutes: int) -> None:
        """Deliver a one-time verification code to the user's corporate email."""


class ConsoleEmailSender(EmailSender):
    """Local development sender. Refuses to log OTPs in production."""

    def send_otp(self, email: str, code: str, expires_minutes: int) -> None:
        if settings.ENVIRONMENT.lower() == "production":
            raise RuntimeError("ConsoleEmailSender cannot be used in production.")
        print(
            f"[DEV EMAIL OTP] To: {email} | Code: {code} | Expires in {expires_minutes} min",
            flush=True,
        )


def get_email_sender() -> EmailSender:
    mode = settings.EMAIL_SENDER_MODE.strip().lower()
    if mode == "console":
        return ConsoleEmailSender()
    raise NotImplementedError(f"Email sender mode '{mode}' is not configured yet.")
