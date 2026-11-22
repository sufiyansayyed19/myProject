import uuid
import httpx

from app.core.config import settings
from app.core.errors import AppError


class ParkingDependencyClient:
    """Calls Parking Service's internal booking-dependency endpoint before mutating/deactivating a vehicle."""

    def has_blocking_booking(self, vehicle_id: uuid.UUID, request_id: str | None = None) -> bool:
        url = f"{settings.PARKING_SERVICE_URL.rstrip('/')}/internal/v1/vehicles/{vehicle_id}/booking-dependency"
        headers = {"X-Internal-Service-Token": settings.VEHICLE_TO_PARKING_TOKEN}
        if request_id:
            headers["X-Request-ID"] = request_id

        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(url, headers=headers)
        except httpx.HTTPError:
            raise AppError(
                503,
                "PARKING_SERVICE_UNAVAILABLE",
                "Cannot verify booking dependencies because Parking Service is unavailable.",
            )

        if resp.status_code != 200:
            raise AppError(
                503,
                "PARKING_SERVICE_UNAVAILABLE",
                "Parking Service failed to verify booking dependencies.",
            )

        try:
            data = resp.json()
            return bool(data["has_blocking_booking"])
        except (ValueError, KeyError, TypeError):
            raise AppError(
                503,
                "PARKING_SERVICE_UNAVAILABLE",
                "Invalid booking dependency response from Parking Service.",
            )


def get_parking_client() -> ParkingDependencyClient:
    return ParkingDependencyClient()
