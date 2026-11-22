import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user_id
from app.models.vehicle import Vehicle
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleDeactivateResponse,
    VehicleListResponse,
    VehicleResponse,
    VehicleUpdate,
)
from app.services.parking_client import ParkingDependencyClient, get_parking_client

router = APIRouter(prefix="/api/v1/vehicles", tags=["vehicles"])


def _get_owned_active_vehicle(db: Session, vehicle_id: uuid.UUID, user_id: uuid.UUID) -> Vehicle:
    vehicle = db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.user_id == user_id,
            Vehicle.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vehicle is None:
        raise AppError(404, "VEHICLE_NOT_FOUND", "Vehicle not found.")
    return vehicle


@router.post("", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    payload: VehicleCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    existing = db.execute(
        select(Vehicle).where(
            Vehicle.user_id == user_id,
            Vehicle.vehicle_number == payload.vehicle_number,
            Vehicle.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError(409, "VEHICLE_ALREADY_REGISTERED", "An active vehicle with this number is already registered.")

    vehicle = Vehicle(
        user_id=user_id,
        vehicle_number=payload.vehicle_number,
        vehicle_type=payload.vehicle_type,
        is_ev=payload.is_ev,
        is_active=True,
    )
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "VEHICLE_ALREADY_REGISTERED", "An active vehicle with this number is already registered.")

    db.refresh(vehicle)
    return VehicleResponse.model_validate(vehicle)


@router.get("", response_model=VehicleListResponse)
def list_vehicles(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(Vehicle)
        .where(Vehicle.user_id == user_id, Vehicle.is_active.is_(True))
        .order_by(Vehicle.created_at.asc())
    ).scalars().all()
    return VehicleListResponse(vehicles=[VehicleResponse.model_validate(v) for v in rows])


@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(
    vehicle_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    vehicle = _get_owned_active_vehicle(db, vehicle_id, user_id)
    return VehicleResponse.model_validate(vehicle)


@router.put("/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: uuid.UUID,
    payload: VehicleUpdate,
    request: Request,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    parking_client: ParkingDependencyClient = Depends(get_parking_client),
):
    vehicle = _get_owned_active_vehicle(db, vehicle_id, user_id)

    request_id = getattr(request.state, "request_id", None)
    if parking_client.has_blocking_booking(vehicle_id=vehicle.id, request_id=request_id):
        raise AppError(
            409,
            "VEHICLE_HAS_BLOCKING_BOOKING",
            "Vehicle cannot be updated while an active or future booking depends on it.",
        )

    duplicate = db.execute(
        select(Vehicle).where(
            Vehicle.user_id == user_id,
            Vehicle.vehicle_number == payload.vehicle_number,
            Vehicle.is_active.is_(True),
            Vehicle.id != vehicle.id,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise AppError(409, "VEHICLE_ALREADY_REGISTERED", "An active vehicle with this number is already registered.")

    vehicle.vehicle_number = payload.vehicle_number
    vehicle.vehicle_type = payload.vehicle_type
    vehicle.is_ev = payload.is_ev

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "VEHICLE_ALREADY_REGISTERED", "An active vehicle with this number is already registered.")

    db.refresh(vehicle)
    return VehicleResponse.model_validate(vehicle)


@router.delete("/{vehicle_id}", response_model=VehicleDeactivateResponse)
def deactivate_vehicle(
    vehicle_id: uuid.UUID,
    request: Request,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    parking_client: ParkingDependencyClient = Depends(get_parking_client),
):
    vehicle = _get_owned_active_vehicle(db, vehicle_id, user_id)

    request_id = getattr(request.state, "request_id", None)
    if parking_client.has_blocking_booking(vehicle_id=vehicle.id, request_id=request_id):
        raise AppError(
            409,
            "VEHICLE_HAS_BLOCKING_BOOKING",
            "Vehicle cannot be removed while an active or future booking depends on it.",
        )

    vehicle.is_active = False
    db.commit()

    return VehicleDeactivateResponse(
        id=vehicle.id,
        is_active=False,
        message="Vehicle removed successfully",
    )
