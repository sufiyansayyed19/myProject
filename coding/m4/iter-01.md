# Milestone 4 (m4) — Iteration 01: Parking Service Core (5 Public APIs + 100-Slot Seed)

## Goal
Implement the core **Parking Service** (`services/parking-service/`, port `8003`, DB `parking_db`) with its 3 tables, initial Alembic migration + 100-slot seed (`C01`–`C60`, `B01`–`B40`), all business/time/pricing rules, per-user advisory locking + slot row locking, `Idempotency-Key` support, immutable vehicle snapshots, lazy hold expiry, and all 5 public APIs.

## What Was Built

### 1. ORM Models & Alembic Migration (+ 100-Slot Seed)
- `app/models/parking.py` — 3 SQLAlchemy models:
  - `parking_slots` (`id`, `slot_number` unique, `vehicle_type` CHECK `CAR`/`BIKE`, `is_charging_enabled`).
  - `bookings` (`id`, `user_id`, `vehicle_id`, `vehicle_number_snapshot`, `vehicle_type_snapshot`, `is_ev_snapshot`, `slot_id` FK, `booking_date`, `start_time`, `end_time`, `requires_charging`, `status` CHECK, `amount` `NUMERIC(10,2)`, `hold_expires_at`, `payment_id` unique, timestamps, `cancelled_at`).
  - `booking_idempotency_keys` (`user_id`, `idempotency_key` unique pair, `request_hash`, `booking_id` FK).
- `alembic/versions/0001_initial_parking_tables.py` — Creates all 3 tables, constraints, indexes, and bulk-inserts all **100 sample slots** (50 normal car `C01`–`C50`, 10 charging car `C51`–`C60`, 35 normal bike `B01`–`B35`, 5 charging bike `B36`–`B40`).

### 2. Business Rules, Clock & Downstream Clients
- `app/core/clock.py` — Controllable `get_now()` dependency in `Asia/Kolkata` (with IST fallback on Windows).
- `app/services/rules.py` — Enforces today/tomorrow horizon, Sunday closure, 07:00–22:00 whole-hour slots, max 12h duration, strictly `> 15 min` advance notice, same-hour rule (`0–30 min` stores nominal whole-hour block & charges full 1h rate), EV charging compatibility, ₹10/hr vs ₹20/hr pricing, and strictly `> 5 min` cancellation cutoff.
- `app/services/clients.py` — `VehicleServiceClient` (forwards user Bearer JWT + `PARKING_TO_VEHICLE_TOKEN`) and `PaymentServiceClient` (2 inline attempts with `PARKING_TO_PAYMENT_TOKEN`).

### 3. All 5 Public API Endpoints (`app/api/v1/parking.py`)
1. `GET /api/v1/parking/availability` — Informational compatible-slot count & hourly rate.
2. `POST /api/v1/parking/bookings` — Requires `Idempotency-Key` UUID header; acquires `pg_advisory_xact_lock` per user + `FOR UPDATE` on compatible slots ordered by `slot_number ASC`; checks user & slot overlap; commits 5-min `PAYMENT_PENDING` hold + snapshots; calls Payment Service and saves `payment_id`.
3. `GET /api/v1/parking/bookings` — Paginated (`page=1, page_size=20`, max `100`) with lazy hold expiry.
4. `GET /api/v1/parking/bookings/{booking_id}` — Owner-scoped detail with lazy hold expiry.
5. `POST /api/v1/parking/bookings/{booking_id}/cancel` — Locks booking, requires `CONFIRMED` and `> 5 min` before start, transitions to `CANCELLED`.

### 4. Automated Tests
- `services/parking-service/tests/test_parking.py` — Tests availability, booking creation + snapshots + pricing, `Idempotency-Key` replay & `409` conflict, user overlap across different vehicles, adjacent intervals, capacity exhaustion, non-EV charging rejection, 15-min advance boundary, same-hour `09:20` vs `09:35`, Sunday closure, 5-min cancellation cutoff (`09:54` vs `09:55`), and lazy hold expiry.

## How to Run & Test Locally

1. **Apply Alembic migration & seed 100 slots into `parking_db`:**
   ```powershell
   cd services/parking-service
   ..\..\.venv\Scripts\alembic.exe upgrade head
   ```
2. **Start Parking Service on port `8003`:**
   ```powershell
   ..\..\.venv\Scripts\uvicorn.exe app.main:app --port 8003 --reload
   ```
3. **Run automated tests:**
   ```powershell
   .venv\Scripts\pytest.exe services/parking-service/tests/test_parking.py -v
   ```
