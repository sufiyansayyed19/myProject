from datetime import datetime, timezone
import time
import uuid

import httpx

from app.core.config import settings


class ParkingCallbackClient:
    """Delivers simulated payment outcome to Parking Service with up to 2 inline retries (Q-19)."""

    def deliver_payment_result(
        self,
        booking_id: uuid.UUID,
        payment_id: uuid.UUID,
        status: str,
        transaction_id: str | None,
        processed_at: datetime,
        request_id: str | None = None,
    ) -> tuple[bool, int, str | None]:
        url = f"{settings.PARKING_SERVICE_URL.rstrip('/')}/internal/v1/bookings/{booking_id}/payment-result"
        headers = {"X-Internal-Service-Token": settings.PAYMENT_TO_PARKING_TOKEN}
        if request_id:
            headers["X-Request-ID"] = request_id

        payload = {
            "payment_id": str(payment_id),
            "status": status,
            "transaction_id": transaction_id,
            "processed_at": processed_at.astimezone(timezone.utc).isoformat(),
        }

        last_error: str | None = None
        for attempt in range(1, 3):
            try:
                with httpx.Client(timeout=3.0) as client:
                    resp = client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return True, attempt, None
                last_error = f"HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__

            if attempt < 2:
                time.sleep(0.5)

        return False, 2, last_error


def get_callback_client() -> ParkingCallbackClient:
    return ParkingCallbackClient()
