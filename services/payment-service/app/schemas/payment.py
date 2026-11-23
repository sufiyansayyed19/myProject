from datetime import datetime
from decimal import Decimal
from typing import Literal
import uuid

from pydantic import BaseModel, Field

PaymentMethod = Literal["UPI", "CARD", "WALLET"]


class InternalPaymentCreateRequest(BaseModel):
    booking_id: uuid.UUID
    user_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    expires_at: datetime


class InternalPaymentCreateResponse(BaseModel):
    payment_id: uuid.UUID
    booking_id: uuid.UUID
    amount: Decimal
    status: str
    expires_at: datetime


class PaymentProcessRequest(BaseModel):
    payment_method: PaymentMethod


class PaymentProcessResponse(BaseModel):
    payment_id: uuid.UUID
    booking_id: uuid.UUID
    amount: Decimal
    status: str
    transaction_id: str | None = None


class PaymentDetailResponse(BaseModel):
    payment_id: uuid.UUID
    booking_id: uuid.UUID
    amount: Decimal
    payment_method: str | None = None
    status: str
    transaction_id: str | None = None
    expires_at: datetime
    created_at: datetime
