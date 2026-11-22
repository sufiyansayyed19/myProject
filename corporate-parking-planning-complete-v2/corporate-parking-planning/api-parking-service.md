# Parking Service API Contract

**Document status:** Core service API design. The five public routes and two internal endpoints (payment-result callback and vehicle booking-dependency check) form the **7-endpoint Parking Service baseline**.

## 1. Responsibilities

Parking Service is the authoritative owner of parking slots and bookings. It owns availability, booking validation, slot allocation, temporary holds, fee calculation, cancellation, and booking history.

It calls Vehicle Service to validate vehicle ownership/type/EV/active status. It calls Payment Service to create a payment attempt. It does not read those services' databases.

## 2. Endpoint inventory

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| GET | `/api/v1/parking/availability` | Authenticated user | Informational availability lookup |
| POST | `/api/v1/parking/bookings` | Authenticated user | Create a hold and initiate payment (supports `Idempotency-Key`) |
| GET | `/api/v1/parking/bookings` | Authenticated user | List caller's bookings |
| GET | `/api/v1/parking/bookings/{booking_id}` | Authenticated user | Retrieve one owned booking |
| POST | `/api/v1/parking/bookings/{booking_id}/cancel` | Authenticated user | Cancel eligible confirmed booking |
| POST | `/internal/v1/bookings/{booking_id}/payment-result` | Payment Service only | Apply payment result to booking |
| GET | `/internal/v1/vehicles/{vehicle_id}/booking-dependency` | Vehicle Service only | Check whether vehicle has blocking active/future bookings |

## 3. Booking and response fields

Booking public representation (field names may be finalized with the selected framework/API conventions):

```json
{
  "booking_id": "<booking-uuid>",
  "vehicle_id": "<vehicle-uuid>",
  "vehicle_number_snapshot": "MH12AB1234",
  "vehicle_type_snapshot": "CAR",
  "is_ev_snapshot": true,
  "slot_number": "C07",
  "date": "2026-11-24",
  "start_time": "10:00",
  "end_time": "13:00",
  "requires_charging": true,
  "amount": 60.00,
  "status": "PAYMENT_PENDING",
  "payment_id": "<payment-uuid-or-null>",
  "hold_expires_at": "2026-11-24T14:35:00+05:30"
}
```

`user_id` is not accepted from the client and ordinarily need not be returned. All booking endpoints scope records to the authenticated user's UUID.

## 4. `GET /api/v1/parking/availability`

### Purpose

Show current capacity for the requested vehicle and interval. This endpoint is informational only and does not reserve a slot.

### Query parameters

| Name | Required | Example | Meaning |
|---|---|---|---|
| `date` | Yes | `2026-11-24` | Booking calendar date in Asia/Kolkata |
| `start_time` | Yes | `10:00` | Whole-hour start boundary, subject to same-hour rule |
| `end_time` | Yes | `13:00` | Whole-hour end boundary |
| `vehicle_id` | Yes | `<vehicle-uuid>` | Registered vehicle selected by caller |
| `requires_charging` | Yes | `true` | Booking-specific charging choice |

Example:

```http
GET /api/v1/parking/availability?date=2026-11-24&start_time=10:00&end_time=13:00&vehicle_id=<uuid>&requires_charging=true
```

### Processing

1. Validate date/time rules in `business-rules.md`.
2. Call Vehicle Service and validate ownership, `is_active`, `vehicle_type`, and `is_ev`.
3. Reject `requires_charging=true` for a non-EV.
4. Derive the compatible slot pool: same vehicle type; charging-enabled only when charging is requested.
5. Exclude intervals overlapping confirmed bookings or valid payment holds.
6. Return the current count.

Overlap predicate:

```text
new_start < existing_end AND new_end > existing_start
```

Boundary-touching intervals do not overlap.

### Response

`200 OK`

```json
{
  "available": true,
  "available_slots": 3,
  "vehicle_type": "CAR",
  "is_ev": true,
  "requires_charging": true,
  "rate_per_hour": 20.00
}
```

When no compatible capacity exists, return `available=false` and `available_slots=0`. Availability is a snapshot, not a promise. Booking creation must re-check atomically.

### Errors

- `400/422 INVALID_BOOKING_INTERVAL` — malformed or invalid date/time interval.
- `401 UNAUTHENTICATED` — missing/invalid user token.
- `404 VEHICLE_NOT_FOUND` — vehicle doesn't exist, is inactive, or is not owned by caller.
- `422 CHARGING_NOT_SUPPORTED` — non-EV requests charging.
- `503 VEHICLE_SERVICE_UNAVAILABLE` — vehicle validation cannot be completed.

## 5. `POST /api/v1/parking/bookings`

### Purpose

Atomically allocate a compatible slot, create a five-minute payment hold, and initiate a payment attempt.

### Request headers & body

**Agreed idempotency header:**

```http
Idempotency-Key: <client-generated-uuid>
```

- Persisted in Parking Service, uniquely scoped to the authenticated user (`user_id` + `idempotency_key`) and associated with the created booking so duplicate requests cannot create multiple holds.
- Same user + same key + same request payload: return the original booking result without creating another booking.
- Same user + same key + different payload: return `409 Conflict`.

```json
{
  "vehicle_id": "<vehicle-uuid>",
  "date": "2026-11-24",
  "start_time": "10:00",
  "end_time": "13:00",
  "requires_charging": true
}
```

The client must not submit `user_id`, `slot_id`, `amount`, `status`, `payment_id`, or `hold_expires_at`. These are server-owned values.

### Validation

- Validate `Idempotency-Key` header (UUID) and check for an existing idempotency record scoped to the authenticated user.
- Validate business date, operating day, operating hours, booking horizon and duration.
- Apply the strict more-than-15-minute minimum-advance rule for future whole-hour start times.
- Apply the agreed same-hour exception: within the first 30 minutes of the current hour, accept the nominal whole-hour block (e.g., `09:00–10:00` at `09:20`), store `start_time = 09:00` and `end_time = 10:00`, and charge the full one-hour rate with no prorating.
- Validate the selected vehicle through Vehicle Service and capture immutable snapshots (`vehicle_number_snapshot`, `vehicle_type_snapshot`, `is_ev_snapshot`) on the booking record.
- Validate EV/charging compatibility.
- Prevent overlapping active bookings for the same user, even across different vehicles.
- Find a compatible slot.
- Re-check candidate capacity inside a PostgreSQL transaction with locking before writing the hold.

### Booking creation and payment initiation sequence

1. Validate request and vehicle.
2. Begin Parking DB transaction.
3. Serialize/check same-user booking conflict and lock/re-check compatible slot candidates.
4. Create booking with `PAYMENT_PENDING`, chosen `slot_id`, computed `amount`, and `hold_expires_at = now + 5 minutes`.
5. Commit the booking hold.
6. Call Payment Service's internal create-payment operation with booking ID, owner user ID, amount and expiry.
7. Save returned `payment_id` to the booking.
8. Return the booking and payment reference to the frontend.

**Important unresolved failure window:** the Parking transaction and Payment Service database transaction cannot be one atomic distributed transaction. The exact behavior if the Payment Service is unavailable after the hold commits must be finalized in `workflows-and-reliability.md`. Recommended behavior: retry the idempotent payment-create call using the same booking ID while the hold remains valid; if no payment can be established before expiry, expire the booking and allow capacity to reopen. Do not create a second booking as an automatic retry.

### Success response

`201 Created` after a payment attempt has been created successfully:

```json
{
  "booking_id": "<booking-uuid>",
  "vehicle_id": "<vehicle-uuid>",
  "slot_number": "C07",
  "date": "2026-11-24",
  "start_time": "10:00",
  "end_time": "13:00",
  "requires_charging": true,
  "amount": 60.00,
  "status": "PAYMENT_PENDING",
  "payment_id": "<payment-uuid>",
  "hold_expires_at": "2026-11-24T14:35:00+05:30"
}
```

Payment success is not implied by this response. The booking is not confirmed until a valid callback is accepted.

### Errors

| HTTP | Example code | Meaning |
|---:|---|---|
| 400/422 | `INVALID_BOOKING_REQUEST` | Invalid fields, date/time, duration, or policy violation |
| 401 | `UNAUTHENTICATED` | User authentication invalid |
| 404 | `VEHICLE_NOT_FOUND` | Vehicle isn't available to caller |
| 409 | `USER_BOOKING_OVERLAP` | Caller already has an overlapping active booking |
| 409 | `NO_PARKING_CAPACITY` | No compatible slot remains at transaction time |
| 503 | `VEHICLE_SERVICE_UNAVAILABLE` | Cannot validate vehicle |
| 503 | `PAYMENT_SERVICE_UNAVAILABLE` | Payment creation cannot be established; exact hold cleanup/retry behavior is specified separately |

The exact distinction between `400` and `422` for semantic policy violations is part of the common error convention and can be finalized later; do not allow inconsistent status choices across services.

## 6. `GET /api/v1/parking/bookings`

### Purpose

List the authenticated user's bookings, including current and historical states.

### Request

No `user_id` parameter. Pagination is recommended:

```http
GET /api/v1/parking/bookings?page=1&page_size=20
```

`page` and `page_size` are proposed defaults (page 1, size 20); maximum page size should be capped. Status/date filters are not required for the initial scope.

### Response

`200 OK`

```json
{
  "items": [
    {
      "booking_id": "<booking-uuid>",
      "vehicle_id": "<vehicle-uuid>",
      "slot_number": "C07",
      "date": "2026-11-24",
      "start_time": "10:00",
      "end_time": "13:00",
      "requires_charging": true,
      "amount": 60.00,
      "status": "CONFIRMED",
      "payment_id": "<payment-uuid>"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total_items": 1
}
```

The authenticated user's UUID is added as a server-side filter. The exact pagination envelope can be aligned with the overall API convention.

## 7. `GET /api/v1/parking/bookings/{booking_id}`

### Purpose

Retrieve details/status of one booking owned by the authenticated user.

### Response

`200 OK` with the booking representation.

### Errors

- `401 UNAUTHENTICATED`
- `404 BOOKING_NOT_FOUND` for nonexistent or non-owned bookings.

## 8. `POST /api/v1/parking/bookings/{booking_id}/cancel`

### Purpose

Cancel an eligible confirmed booking while preserving history.

### Processing

1. Find booking scoped by `booking_id` and authenticated `user_id`.
2. Lock the booking row to avoid a race with a payment callback or another cancellation.
3. Require `status=CONFIRMED`.
4. Require current time to be strictly more than five minutes before the booking start instant, interpreted in `Asia/Kolkata`.
5. Change status to `CANCELLED`, set `cancelled_at`, and update `updated_at`.
6. Do not delete the booking or call a slot-release endpoint. Availability is derived from state.

### Response

`200 OK`

```json
{
  "booking_id": "<booking-uuid>",
  "status": "CANCELLED",
  "cancelled_at": "2026-11-24T09:54:00+05:30"
}
```

### Errors

- `401 UNAUTHENTICATED`
- `404 BOOKING_NOT_FOUND`
- `409 BOOKING_NOT_CANCELLABLE` — payment pending, expired, already cancelled, or within the five-minute cutoff.

The existing rule permits cancellation only for confirmed bookings. The exact public error-code distinction among the cases is not yet fixed.

## 9. Internal `POST /internal/v1/bookings/{booking_id}/payment-result`

### Caller

Payment Service only. Must not be exposed via public Gateway routing.

### Request

```json
{
  "payment_id": "<payment-uuid>",
  "status": "SUCCESS",
  "transaction_id": "TXN83921",
  "processed_at": "2026-11-24T14:33:00+05:30"
}
```

For `FAILED`, `transaction_id` is null. Only `SUCCESS` and `FAILED` are valid final results.

### Processing

- Authenticate the Payment Service caller.
- Lock the booking.
- Verify that the supplied payment ID matches the booking's recorded payment ID.
- If state is `PAYMENT_PENDING` and the hold remains valid: `SUCCESS` becomes `CONFIRMED`; `FAILED` becomes `EXPIRED`.
- If the hold has expired, do not allow late success to resurrect the booking; it remains/becomes `EXPIRED`. Use Parking Service/database time for the expiry decision. The callback `processed_at` value is event metadata, not the authority for deciding whether the hold was valid.
- If the exact same final callback is repeated, acknowledge idempotently without repeating side effects.
- If a conflicting or mismatched callback arrives, reject and log it for investigation.

### Response

Successful processing or already-applied identical callback: `200 OK`.

```json
{
  "booking_id": "<booking-uuid>",
  "status": "CONFIRMED",
  "result": "APPLIED"
}
```

Idempotent duplicate response may use `result: "ALREADY_APPLIED"`.

### Errors

- `401/403` — internal caller authentication failure.
- `404 BOOKING_NOT_FOUND` — booking does not exist.
- `409 PAYMENT_REFERENCE_MISMATCH` — callback payment ID does not match.
- `409 INVALID_BOOKING_TRANSITION` — conflicting callback/state transition.

## 10. State model

```text
PAYMENT_PENDING
  ├── SUCCESS while hold valid ──> CONFIRMED
  ├── FAILED ────────────────────> EXPIRED
  └── hold timeout ──────────────> EXPIRED

CONFIRMED
  └── eligible cancellation ────> CANCELLED
```

No `ALLOCATED`, `RELEASED`, `COMPLETED`, or session state is currently needed.

## 11. Availability and overlap rules

A candidate slot is compatible when:

- its `vehicle_type` matches the selected vehicle;
- if charging is requested, `is_charging_enabled=true`;
- no `CONFIRMED` booking overlaps the requested interval;
- no `PAYMENT_PENDING` booking with a still-valid hold overlaps the interval.

`CANCELLED` and `EXPIRED` bookings do not block capacity. A stale pending row whose hold expiry has passed must not block capacity indefinitely; the lifecycle/reconciliation plan must ensure it is transitioned to `EXPIRED`.

For a given slot, intervals are half-open for overlap semantics: end at 10:00 and next start at 10:00 do not overlap.

## 12. Internal `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` (Approved)

**Status: Agreed** (included in the 7-endpoint Parking Service baseline).

Called by Vehicle Service (with internal service authentication; never exposed through the Gateway) before updating or deactivating a vehicle.

```http
GET /internal/v1/vehicles/{vehicle_id}/booking-dependency
```

Response (`200 OK`):

```json
{
  "has_blocking_booking": true,
  "blocking_booking_count": 1
}
```

**Agreed definition of a blocking booking:**
- A future or currently active `CONFIRMED` booking, OR
- A valid, unexpired `PAYMENT_PENDING` booking.

Historical, `CANCELLED`, `EXPIRED`, and already-ended bookings do not block mutation.

## 13. Finalized operational decisions (m0)

- Concurrency: single `READ COMMITTED` transaction using `pg_advisory_xact_lock` per user + `SELECT ... FROM parking_slots ORDER BY slot_number ASC FOR UPDATE` + overlap recheck.
- Expired holds: lazy expiry on availability/read/callback (no background worker).
- Payment creation recovery: up to 2 inline attempts (3s timeout); returns `503` if Payment Service remains unavailable.
- Common error envelope: `{ "error": { "code": "...", "message": "...", "request_id": "..." } }` (`400` malformed syntax, `422` validation, `409` conflicts).
