from datetime import date, datetime, time
from decimal import Decimal
import uuid

from pydantic import BaseModel, Field


class AvailabilityResponse(BaseModel):
    available: bool
    available_slots: int
    vehicle_type: str
    is_ev: bool
    requires_charging: bool
    rate_per_hour: Decimal


class BookingCreateRequest(BaseModel):
    vehicle_id: uuid.UUID
    date: date
    start_time: time
    end_time: time
    requires_charging: bool = False


class BookingResponse(BaseModel):
    booking_id: uuid.UUID
    vehicle_id: uuid.UUID
    vehicle_number_snapshot: str
    vehicle_type_snapshot: str
    is_ev_snapshot: bool
    slot_number: str
    date: date
    start_time: str
    end_time: str
    requires_charging: bool
    amount: Decimal
    status: str
    payment_id: uuid.UUID | None = None
    hold_expires_at: datetime | None = None
    cancelled_at: datetime | None = None


class BookingListResponse(BaseModel):
    items: list[BookingResponse]
    page: int
    page_size: int
    total_items: int


class BookingCancelResponse(BaseModel):
    booking_id: uuid.UUID
    status: str = Field(default="CANCELLED")
    cancelled_at: datetime
