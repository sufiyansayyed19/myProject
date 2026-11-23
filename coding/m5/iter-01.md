# Milestone 5 (m5) — Iteration 01: Payment Service (3 APIs) & Parking Internal APIs (2 APIs)

## Goal
Complete all remaining business APIs (**22 of 22 total**):
- **Payment Service** (`services/payment-service/`, port `8004`, DB `payment_db`): `payments` table, Alembic migration, deterministic simulated payment gateway (`UPI`/`CARD`/`WALLET`), and 2 inline callback retries to Parking.
- **Parking Service Internal APIs** (`services/parking-service/app/api/internal.py`): payment-result callback (idempotent, never resurrects expired holds) and vehicle booking-dependency check.

## What Was Built

### 1. Payment Service (`services/payment-service/`)
- `app/models/payment.py` & `alembic/versions/0001_initial_payment_tables.py` — `payments` table with `UNIQUE(booking_id)`, `UNIQUE(transaction_id)`, `CHECK (amount > 0)`, `CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED'))`, `CHECK (payment_method IN ('UPI', 'CARD', 'WALLET'))`, and callback tracking columns.
- `app/services/parking_callback.py` — Delivers `POST /internal/v1/bookings/{booking_id}/payment-result` with `X-Internal-Service-Token: PAYMENT_TO_PARKING_TOKEN` and up to 2 inline retries (0.5s pause).
- `app/api/v1/payments.py` — 3 endpoints:
  1. `POST /internal/v1/payments` — Internal Parking-only endpoint; idempotent by `booking_id` (`201` new, `200` identical replay, `409` conflicting values).
  2. `POST /api/v1/payments/{payment_id}/process` — Owner-scoped simulated payment (`UPI`/`CARD`/`WALLET`), backend-controlled via `PAYMENT_SIMULATION_DEFAULT_OUTCOME` + non-prod `X-Test-Payment-Outcome` override; persists result BEFORE sending callback; returns `409 PAYMENT_ALREADY_PROCESSED` on duplicate and `409 PAYMENT_EXPIRED` after expiry.
  3. `GET /api/v1/payments/{payment_id}` — Owner-scoped payment details (`404` for non-owned).

### 2. Parking Service Internal Endpoints (`services/parking-service/app/api/internal.py`)
1. `POST /internal/v1/bookings/{booking_id}/payment-result` — Authenticated via `PAYMENT_TO_PARKING_TOKEN`; locks booking, validates `payment_id`, transitions `PAYMENT_PENDING` → `CONFIRMED` or `EXPIRED` using Parking's own clock, handles duplicate callbacks idempotently, and **never resurrects expired holds**.
2. `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` — Authenticated via `VEHICLE_TO_PARKING_TOKEN`; reports active/future `CONFIRMED` or unexpired `PAYMENT_PENDING` bookings so Vehicle Service blocks unsafe edits/deactivation with `409`.

### 3. Automated Tests
- `services/payment-service/tests/test_payments.py` — Tests internal auth, idempotent creation & conflict, owner isolation, `SUCCESS`, `X-Test-Payment-Outcome: FAILED` override, duplicate `409`, and expiry `409`.
- `services/parking-service/tests/test_internal.py` — Tests payment callback confirmation, duplicate callback idempotency, late-success no-resurrection, and vehicle booking-dependency rules.

## How to Run Locally
1. **Migrate `payment_db`:**
   ```powershell
   cd services\payment-service
   ..\..\.venv\Scripts\alembic.exe upgrade head
   ```
2. **Start Payment Service on port `8004`:**
   ```powershell
   ..\..\.venv\Scripts\uvicorn.exe app.main:app --port 8004 --reload
   ```
3. **Run tests:**
   ```powershell
   .venv\Scripts\pytest.exe services/payment-service/tests/test_payments.py services/parking-service/tests/test_internal.py -v
   ```
