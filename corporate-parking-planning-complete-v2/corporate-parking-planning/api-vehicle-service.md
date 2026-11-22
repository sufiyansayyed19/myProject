# Vehicle Service API Contract

**Document status:** Technical design baseline. The five-route inventory is retained. Cross-service restrictions marked **Proposed/Open** need resolution before implementation.

## 1. Responsibilities and boundaries

Vehicle Service is the authoritative owner of registered vehicle master data. It supports `CAR` and `BIKE`, the EV flag, ownership by application user ID, and active/inactive status.

It does not allocate slots, calculate fees, or own bookings. `user_id` is derived from authenticated identity and is a logical reference to User/Auth data, not a cross-database foreign key.

## 2. Vehicle representation

```json
{
  "id": "<vehicle-uuid>",
  "vehicle_number": "MH12AB1234",
  "vehicle_type": "CAR",
  "is_ev": true,
  "is_active": true
}
```

`requires_charging` is not a vehicle attribute. It is selected for each booking.

## 3. Endpoint inventory

| Method | Endpoint | Purpose | Current status |
|---|---|---|---|
| POST | `/api/v1/vehicles` | Register a vehicle | In current inventory |
| GET | `/api/v1/vehicles` | List current user's vehicles | In current inventory |
| GET | `/api/v1/vehicles/{vehicle_id}` | Retrieve one owned vehicle | In current inventory |
| PUT | `/api/v1/vehicles/{vehicle_id}` | Replace editable vehicle data | In current inventory |
| DELETE | `/api/v1/vehicles/{vehicle_id}` | Deactivate a vehicle (soft delete) | In current inventory |

No client endpoint accepts `user_id` as an ownership selector.

## 4. Shared authentication and data rules

- All five endpoints require application authentication.
- The authenticated user UUID is extracted from the validated access token's `sub` claim.
- Every read/update/delete query must be scoped by both `vehicle_id` and authenticated `user_id`.
- A vehicle belonging to another user should be treated as not found (`404`) to avoid disclosing its existence.
- Vehicle numbers should be normalized consistently before comparison and persistence.
- `vehicle_type` is restricted to `CAR` or `BIKE`.
- `is_ev` and `is_active` are booleans.

## 5. `POST /api/v1/vehicles`

### Purpose

Register a vehicle once so it can be selected in later booking requests.

### Request

```json
{
  "vehicle_number": "MH12 AB 1234",
  "vehicle_type": "CAR",
  "is_ev": true
}
```

### Validation and processing

1. Require a non-empty vehicle number within the supported length.
2. Normalize the vehicle number. Recommended normalization: uppercase and remove whitespace and permitted separators such as hyphens. The exact accepted registration-number grammar is a project validation decision; do not claim official registration/RC verification.
3. Validate `vehicle_type` is `CAR` or `BIKE`.
4. Require a boolean `is_ev`.
5. Set `user_id` from the authenticated identity; never accept it from the request body.
6. Set `is_active=true` and generate the vehicle UUID.
7. Enforce duplicate-registration policy at database level as well as in application validation.

### Response

`201 Created`

```json
{
  "id": "<vehicle-uuid>",
  "vehicle_number": "MH12AB1234",
  "vehicle_type": "CAR",
  "is_ev": true,
  "is_active": true
}
```

### Errors

| HTTP | Example code | Meaning |
|---:|---|---|
| 400/422 | `INVALID_VEHICLE_DATA` | Invalid/missing field or invalid type |
| 401 | `UNAUTHENTICATED` | Missing/invalid access token |
| 409 | `VEHICLE_ALREADY_REGISTERED` | Duplicate active registration under the same user |

**Proposed duplicate policy:** enforce uniqueness for active `(user_id, normalized_vehicle_number)` records. This allows a previously deactivated vehicle to be registered again as a new active record while retaining the historical inactive record. Confirm this policy before migration design.

## 6. `GET /api/v1/vehicles`

### Purpose

List the authenticated user's registered vehicles for selection during booking.

### Request

No required query parameters.

### Response

`200 OK`

```json
{
  "vehicles": [
    {
      "id": "<vehicle-uuid-1>",
      "vehicle_number": "MH12AB1234",
      "vehicle_type": "CAR",
      "is_ev": true,
      "is_active": true
    },
    {
      "id": "<vehicle-uuid-2>",
      "vehicle_number": "MH05XY4567",
      "vehicle_type": "BIKE",
      "is_ev": false,
      "is_active": true
    }
  ]
}
```

**Proposed default:** return active vehicles only. An optional inactive-history filter is not currently needed. The exact empty-list representation is `{"vehicles": []}`.

## 7. `GET /api/v1/vehicles/{vehicle_id}`

### Purpose

Retrieve one vehicle. Parking Service also needs an authorized server-to-server way to validate a selected vehicle, but the owner-scoped route can be reused if the original user's identity is securely propagated and internal caller authorization is handled.

### Response

`200 OK` with the Vehicle representation.

### Errors

- `401 UNAUTHENTICATED` — invalid/missing user access token.
- `404 VEHICLE_NOT_FOUND` — nonexistent vehicle, vehicle belonging to another user, or inactive vehicle when the chosen contract hides inactive records.

**Open:** decide whether an authenticated owner can retrieve their own inactive vehicle by ID. The default list should not present inactive records as selectable.

## 8. `PUT /api/v1/vehicles/{vehicle_id}`

### Purpose

Replace the editable vehicle fields. This is a full update, not a partial patch.

### Request

```json
{
  "vehicle_number": "MH12AB9999",
  "vehicle_type": "CAR",
  "is_ev": false
}
```

All editable fields are required. `user_id`, `id`, `is_active`, and timestamps are server-managed and must not be accepted as user-controlled fields.

### Validation and processing

- Apply the same normalization and enum validation as creation.
- Enforce duplicate constraints, excluding the record currently being updated.
- Do not allow a user to transfer a vehicle to another user through this endpoint.
- The planned business rule is to block a change to vehicle type or EV classification while a booking depends on the old attributes.

### Service-boundary dependency — Agreed

Vehicle Service cannot query Parking's database to detect bookings. Before updating or deactivating a vehicle, Vehicle Service calls Parking Service's approved internal endpoint:

```http
GET /internal/v1/vehicles/{vehicle_id}/booking-dependency
```

Response:

```json
{
  "has_blocking_booking": true,
  "blocking_booking_count": 1
}
```

**Agreed blocking definition:** a vehicle has a blocking booking if it has either:
- a future or currently active `CONFIRMED` booking, or
- a valid, unexpired `PAYMENT_PENDING` booking.

Historical, `CANCELLED`, `EXPIRED`, and already-ended bookings do not block updates or deactivation. If `has_blocking_booking` is `true`, Vehicle Service rejects the update/deactivation with `409 Conflict` (`VEHICLE_HAS_BLOCKING_BOOKING`). If Parking Service cannot be reached, fail closed with `503 PARKING_SERVICE_UNAVAILABLE`.

### Response

`200 OK` with the updated vehicle representation.

### Errors

- `401 UNAUTHENTICATED`
- `404 VEHICLE_NOT_FOUND`
- `409 VEHICLE_HAS_BLOCKING_BOOKING`
- `409 VEHICLE_ALREADY_REGISTERED`
- `422 INVALID_VEHICLE_DATA`
- `503 PARKING_SERVICE_UNAVAILABLE` if the dependency check is adopted and Parking cannot be reached; fail closed rather than making an unsafe change.

## 9. `DELETE /api/v1/vehicles/{vehicle_id}`

### Purpose

Remove a vehicle from the active vehicle selector without destroying the record referenced by historical bookings.

### Semantics

This is a soft deactivation:

```text
is_active = false
```

It is not a physical SQL `DELETE`.

### Business behavior

- The user's vehicle must exist and be owned by the caller.
- A vehicle with a blocking future/active booking cannot be deactivated under the proposed policy; the booking must first be cancelled or expire.
- Historical bookings alone do not prevent deactivation.
- The inactive row is retained so logical references from old bookings remain meaningful.

### Response

`200 OK`

```json
{
  "id": "<vehicle-uuid>",
  "is_active": false,
  "message": "Vehicle removed successfully"
}
```

### Errors

- `401 UNAUTHENTICATED`
- `404 VEHICLE_NOT_FOUND`
- `409 VEHICLE_HAS_BLOCKING_BOOKING`
- `503 PARKING_SERVICE_UNAVAILABLE` if the approved dependency check is unavailable.

## 10. Historical-data policy — Agreed

Bookings retain `vehicle_id` as a logical reference **and** capture immutable vehicle snapshot fields (`vehicle_number_snapshot`, `vehicle_type_snapshot`, `is_ev_snapshot`) at booking creation time. This ensures historical booking records remain accurate even if the vehicle is later updated or deactivated, while Vehicle Service remains the authoritative owner of current vehicle master data.

## 11. Not included

- RC/document upload or government verification.
- A separate vehicle-registration approval workflow.
- User-supplied `user_id` filters.
- A user endpoint to choose a specific parking slot.
- `requires_charging` on the Vehicle record.
- Hard deletion of vehicle records referenced by bookings.
