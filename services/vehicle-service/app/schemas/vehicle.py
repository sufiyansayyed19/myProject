import re
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, field_validator

VehicleType = Literal["CAR", "BIKE"]
_PLATE_PATTERN = re.compile(r"^[A-Z0-9]{4,20}$")


def normalize_vehicle_number(raw: str) -> str:
    cleaned = re.sub(r"[\s-]+", "", raw.strip()).upper()
    if not _PLATE_PATTERN.match(cleaned):
        raise ValueError("Vehicle number must be 4-20 alphanumeric characters.")
    return cleaned


class VehicleCreate(BaseModel):
    vehicle_number: str
    vehicle_type: VehicleType
    is_ev: bool

    @field_validator("vehicle_number")
    @classmethod
    def validate_plate(cls, v: str) -> str:
        return normalize_vehicle_number(v)


class VehicleUpdate(BaseModel):
    vehicle_number: str
    vehicle_type: VehicleType
    is_ev: bool

    @field_validator("vehicle_number")
    @classmethod
    def validate_plate(cls, v: str) -> str:
        return normalize_vehicle_number(v)


class VehicleResponse(BaseModel):
    id: uuid.UUID
    vehicle_number: str
    vehicle_type: VehicleType
    is_ev: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class VehicleListResponse(BaseModel):
    vehicles: list[VehicleResponse]


class VehicleDeactivateResponse(BaseModel):
    id: uuid.UUID
    is_active: bool
    message: str
