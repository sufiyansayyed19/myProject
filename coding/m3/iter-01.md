# Milestone 3 (m3) — Iteration 01: Vehicle Service (5 APIs)

## Goal
Implement the complete **Vehicle Service** (`services/vehicle-service/`, port `8002`, DB `vehicle_db`) with its `vehicles` table, first Alembic migration, RS256 JWT authentication + `HTTPBearer` Swagger support, plate normalization, soft deactivation with re-registration support (`Q-21`), Parking dependency check client (`GET /internal/v1/vehicles/{vehicle_id}/booking-dependency`), and automated tests.

## What Was Built

### 1. ORM Model & Alembic Migration
- `app/models/vehicle.py` — `Vehicle` (`vehicles` table) with:
  - `id`, `user_id` (logical UUID ref, no cross-DB FK), `vehicle_number`, `vehicle_type` (`CHECK IN ('CAR', 'BIKE')`), `is_ev`, `is_active`, `created_at`, `updated_at`.
  - Partial unique index `uq_vehicles_active_user_number` on `(user_id, vehicle_number) WHERE is_active = true` so deactivated vehicles preserve history while allowing re-registration as a new active row.
- `alembic/versions/0001_initial_vehicle_tables.py` — First migration for `vehicle_db`.

### 2. Security, Error Envelope & Parking Client
- `app/core/security.py` — Validates RS256 Bearer JWT using `keys/jwt_public.pem` (`HTTPBearer` enabled for Swagger Authorize). Also validates `X-Internal-Service-Token` when `Parking Service` calls `GET /api/v1/vehicles/{vehicle_id}`.
- `app/core/errors.py` — Standard m0 error envelope (`{ "error": { "code", "message", "request_id" } }`).
- `app/services/parking_client.py` — Calls Parking Service's `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` with `X-Internal-Service-Token: VEHICLE_TO_PARKING_TOKEN` and fails closed (`503 PARKING_SERVICE_UNAVAILABLE`) if Parking is unreachable.

### 3. All 5 API Endpoints (`app/api/v1/vehicles.py`)
1. `POST /api/v1/vehicles` — Registers an active vehicle for the authenticated user (normalizes registration number: uppercase, strips spaces/hyphens).
2. `GET /api/v1/vehicles` — Lists the caller's active vehicles (`{"vehicles": [...]}`).
3. `GET /api/v1/vehicles/{vehicle_id}` — Owner-scoped active vehicle lookup (`404` for missing, inactive, or non-owned).
4. `PUT /api/v1/vehicles/{vehicle_id}` — Full update; checks Parking booking dependency first (`409 VEHICLE_HAS_BLOCKING_BOOKING` if blocked).
5. `DELETE /api/v1/vehicles/{vehicle_id}` — Soft deactivation (`is_active = false`); checks Parking booking dependency first.

### 4. Automated Tests
- `services/vehicle-service/tests/test_vehicles.py` — 4 test suites covering CRUD, plate normalization, duplicate active rejection, soft-delete + re-registration, cross-user `404` isolation, `X-Internal-Service-Token` validation, `409` blocking-booking rejection, `503` fail-closed behavior, and `422` invalid vehicle type.

## How to Run & Test Locally

1. **Apply Alembic migration to `vehicle_db`:**
   ```powershell
   cd services/vehicle-service
   ..\..\.venv\Scripts\alembic.exe upgrade head
   ```
2. **Start Vehicle Service:**
   ```powershell
   ..\..\.venv\Scripts\uvicorn.exe app.main:app --port 8002 --reload
   ```
   Open **[http://127.0.0.1:8002/docs](http://127.0.0.1:8002/docs)** → click **Authorize 🔒** → paste your RS256 `access_token` from `user-auth-service` → create & list vehicles!
   *(Note: `PUT` and `DELETE` call Parking Service's internal dependency endpoint, so they will return `503 PARKING_SERVICE_UNAVAILABLE` until Parking Service is running in `m4`/`m5` — that's fail-closed working by design!)*
3. **Run automated tests:**
   ```powershell
   .venv\Scripts\pytest.exe services/vehicle-service/tests/test_vehicles.py -v
   ```
