from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import time
import uuid

import httpx

from app.core.config import settings
from app.core.errors import AppError


@dataclass
class VehicleInfo:
    id: uuid.UUID
    vehicle_number: str
    vehicle_type: str
    is_ev: bool
    is_active: bool


class VehicleServiceClient:
    def get_owned_vehicle(
        self,
        vehicle_id: uuid.UUID,
        bearer_token: str,
        request_id: str | None = None,
    ) -> VehicleInfo:
        url = f"{settings.VEHICLE_SERVICE_URL.rstrip('/')}/api/v1/vehicles/{vehicle_id}"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "X-Internal-Service-Token": settings.PARKING_TO_VEHICLE_TOKEN,
        }
        if request_id:
            headers["X-Request-ID"] = request_id

        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(url, headers=headers)
        except httpx.HTTPError:
            raise AppError(
                503,
                "VEHICLE_SERVICE_UNAVAILABLE",
                "Vehicle Service is currently unavailable.",
            )

        if resp.status_code == 404:
            raise AppError(404, "VEHICLE_NOT_FOUND", "Vehicle not found or inactive.")
        if resp.status_code == 401:
            raise AppError(401, "UNAUTHENTICATED", "Authentication rejected by Vehicle Service.")
        if resp.status_code != 200:
            raise AppError(
                503,
                "VEHICLE_SERVICE_UNAVAILABLE",
                "Failed to validate vehicle with Vehicle Service.",
            )

        try:
            data = resp.json()
            info = VehicleInfo(
                id=uuid.UUID(data["id"]),
                vehicle_number=str(data["vehicle_number"]),
                vehicle_type=str(data["vehicle_type"]),
                is_ev=bool(data["is_ev"]),
                is_active=bool(data["is_active"]),
            )
        except (ValueError, KeyError, TypeError):
            raise AppError(
                503,
                "VEHICLE_SERVICE_UNAVAILABLE",
                "Invalid response received from Vehicle Service.",
            )

        if not info.is_active:
            raise AppError(404, "VEHICLE_NOT_FOUND", "Vehicle is inactive.")
        return info


class PaymentServiceClient:
    def create_payment(
        self,
        booking_id: uuid.UUID,
        user_id: uuid.UUID,
        amount: Decimal,
        expires_at: datetime,
        request_id: str | None = None,
    ) -> uuid.UUID:
        url = f"{settings.PAYMENT_SERVICE_URL.rstrip('/')}/internal/v1/payments"
        headers = {"X-Internal-Service-Token": settings.PARKING_TO_PAYMENT_TOKEN}
        if request_id:
            headers["X-Request-ID"] = request_id

        payload = {
            "booking_id": str(booking_id),
            "user_id": str(user_id),
            "amount": float(amount),
            "expires_at": expires_at.isoformat(),
        }

        # Sprint-demo baseline (Q-08): up to 2 inline attempts (3s timeout)
        for attempt in range(2):
            try:
                with httpx.Client(timeout=3.0) as client:
                    resp = client.post(url, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return uuid.UUID(data["payment_id"])
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            if attempt == 0:
                time.sleep(0.5)

        raise AppError(
            503,
            "PAYMENT_SERVICE_UNAVAILABLE",
            "Payment Service is currently unavailable. Please retry shortly.",
        )


def get_vehicle_client() -> VehicleServiceClient:
    return VehicleServiceClient()


def get_payment_client() -> PaymentServiceClient:
    return PaymentServiceClient()
