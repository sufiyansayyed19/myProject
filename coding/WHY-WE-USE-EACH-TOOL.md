# Why We Use Each Tool & Concept (With Project Examples)

A plain-English learning guide explaining **why** each package and backend pattern exists in our Corporate Parking Reservation System—using real examples from our codebase.

---

## 1. FastAPI — The Web Framework
- **Problem it solves:** Turning Python functions into HTTP REST APIs with automatic JSON parsing, validation, authentication dependencies, and interactive Swagger docs.
- **Without it:** You'd manually parse HTTP requests, write JSON serializers, validate every field by hand, and build API docs manually.
- **Project example:** In `services/vehicle-service/app/api/v1/vehicles.py`, writing:
  ```python
  @router.post("", response_model=VehicleResponse, status_code=201)
  def create_vehicle(payload: VehicleCreate, user_id: uuid.UUID = Depends(get_current_user_id), db: Session = Depends(get_db)):
  ```
  automatically validates the JSON body, checks the RS256 JWT via `Depends`, opens/closes a DB session, formats the response, and generates `/docs`.

---

## 2. Uvicorn — The Server That Runs FastAPI
- **Problem it solves:** FastAPI is just Python code; it cannot listen on a network port (`8000`–`8004`) by itself. Uvicorn is the ASGI web server that accepts HTTP traffic and hands it to FastAPI.
- **Project example:** `uvicorn app.main:app --port 8001 --reload` opens port `8001` for `user-auth-service` and restarts automatically whenever you save a `.py` file.

---

## 3. SQLAlchemy (Synchronous `Session`) — Talking to PostgreSQL in Python
- **Problem it solves:** Writing raw SQL strings everywhere is error-prone and hard to maintain. SQLAlchemy lets you work with Python classes (`User`, `Vehicle`, `Booking`) while managing connection pools and transactions safely.
- **Without it:** You'd manually open/close connections, construct SQL strings, and map raw tuple rows `(id, 'MH12AB1234', ...)` to dictionaries everywhere.
- **Project example:** In `parking-service`, SQLAlchemy lets us combine clean ORM queries with real PostgreSQL locking:
  ```python
  slot_stmt = select(ParkingSlot).where(...).order_by(ParkingSlot.slot_number.asc()).with_for_update()
  ```
  And our `get_db()` dependency guarantees `db.close()` always runs after every request—even if an error happens.

---

## 4. `psycopg` (v3) — The PostgreSQL Driver
- **Problem it solves:** SQLAlchemy is a translator, not a network driver. `psycopg` is the actual PostgreSQL driver that speaks PostgreSQL's binary protocol over TCP port `5432`.
- **Why v3 (`psycopg[binary]`) instead of `psycopg2`:** `psycopg` v3 is the modern official PostgreSQL driver for Python 3.13, and `[binary]` avoids needing C compilers on Windows.
- **Project example:** Every service's `DATABASE_URL` starts with `postgresql+psycopg://...`, telling SQLAlchemy to use `psycopg` v3.

---

## 5. Alembic — Version Control for Your Database Schema
- **Problem it solves:** `Base.metadata.create_all()` can *only* create brand-new tables. If you already have a `bookings` table in `parking_db` and later add `vehicle_number_snapshot`, `create_all()` **does nothing**—your app crashes with `column does not exist` unless you delete all your data and recreate the table.
- **With Alembic:** Every schema change is a versioned Python script (`upgrade()` and `downgrade()`), just like Git commits for your database!
- **Project example:**
  - `services/parking-service/alembic/versions/0001_initial_parking_tables.py` creates `parking_slots`, `bookings`, and `booking_idempotency_keys` **and** seeds all 100 parking slots (`C01`–`C60`, `B01`–`B40`) in one atomic command (`.\scripts\migrate_all.ps1`).
  - If tomorrow you add a `notes` column to `bookings`, you create migration `0002_add_notes.py` and run `alembic upgrade head` without losing any existing bookings.

---

## 6. Pydantic & `pydantic-settings` — Strict Input Validation & Config
- **Problem it solves:**
  1. **Pydantic** stops bad data at the door before it touches your database, and keeps API JSON shapes separate from internal DB models (so you never accidentally leak `code_hash` or `token_hash`).
  2. **`pydantic-settings`** loads `.env` files into typed Python objects so secrets never live in Git.
- **Project example:**
  - When a user sends `{"vehicle_number": "mh 12-ab 1234", "vehicle_type": "TRUCK"}`, `VehicleCreate` normalizes the plate to `"MH12AB1234"` and immediately rejects `"TRUCK"` with `422 INVALID_VEHICLE_DATA`.
  - In `user-auth-service/app/core/config.py`, `Settings()` reads `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from `.env` automatically.

---

## 7. `email-validator` — Validating Email Addresses
- **Problem it solves:** Checking whether `"not-an-email"` or `"alice@@company.com"` is a valid email syntax using regex is notoriously tricky.
- **Project example:** In `user-auth-service`, `email: EmailStr` on `SendCodeRequest` uses `email-validator` to reject malformed emails with `422` before we ever check `COMPANY_EMAIL_DOMAIN` or insert into `verification_codes`.

---

## 8. `httpx` — Making HTTP Calls Between Services (and to Google)
- **Problem it solves:** In a microservice architecture, services **cannot** query each other's databases directly—they must talk over HTTP. Python's standard library (`urllib`) is clunky; `httpx` gives clean timeouts, headers, status codes, both sync (`Client`) and async (`AsyncClient`), and `MockTransport` for tests.
- **Project examples (5 places we use `httpx`):**
  1. **API Gateway (`8000`) → All 4 services:** `httpx.AsyncClient` forwards public `/api/v1/*` requests and preserves `302` redirects + `Set-Cookie` headers.
  2. **User/Auth (`8001`) → Google:** Exchanges OAuth `code` at `https://oauth2.googleapis.com/token` and fetches `/userinfo`.
  3. **Parking (`8003`) → Vehicle (`8002`):** Validates that `vehicle_id` belongs to the caller and checks `is_ev` / `vehicle_type`.
  4. **Parking (`8003`) → Payment (`8004`):** Calls `POST /internal/v1/payments` (with 2 inline retries + 3s timeout).
  5. **Payment (`8004`) → Parking (`8003`):** Delivers `POST /internal/v1/bookings/{id}/payment-result` callback after simulated payment succeeds/fails.

---

## 9. `PyJWT[crypto]` & `cryptography` — RS256 Asymmetric Authentication
- **Problem it solves:** If `vehicle-service`, `parking-service`, and `payment-service` had to call `user-auth-service` on every single API request just to check "who is this user?", `user-auth-service` would become a bottleneck and single point of failure.
- **With RS256 JWT (`PyJWT` + `cryptography`):**
  - `scripts/generate_dev_keys.py` uses `cryptography` to create a **private key** (`jwt_private.pem`) and a **public key** (`jwt_public.pem`).
  - **Only** `user-auth-service` has `jwt_private.pem` to **sign** 15-minute access tokens.
  - `gateway`, `vehicle-service`, `parking-service`, and `payment-service` only have `jwt_public.pem` to **verify** tokens locally in microseconds—they can trust the `sub` (`user_id`) claim, and **cannot forge tokens**!

---

## 10. `pytest` — Automated Safety Net
- **Problem it solves:** Manually clicking 22 endpoints in Swagger every time you change 1 line of code is slow and misses edge cases (like two users clicking "Book" at the exact same millisecond).
- **Project example:** Running `.\scripts\run_all_tests.ps1` automatically tests:
  - OTP expiry/attempts, refresh token rotation, and Google account linking (`test_auth.py`).
  - Plate normalization, soft delete + re-registration, and fail-closed `503` (`test_vehicles.py`).
  - Sunday closure, `08:44` vs `08:45`, `09:20` vs `09:35`, `09:54` vs `09:55` cancel cutoff (`test_parking.py`).
  - **10 simultaneous threads racing for 5 EV-bike slots** against real PostgreSQL (`test_pg_concurrency.py`).
  - Full 10-step live journey across all 5 apps (`test_e2e_journey.py`).

---

## 11. Key Backend Patterns We Used (Bonus for Sprint Q&A)

| Pattern | Without It | Concrete Example in Our Project |
|---|---|---|
| **`Idempotency-Key` header** | User's Wi-Fi drops on `POST /bookings`, app retries → user gets charged twice for 2 slots. | Same user + same `Idempotency-Key` + same payload replays the original booking (`200`); different payload returns `409 IDEMPOTENCY_CONFLICT`. |
| **`pg_advisory_xact_lock` + `FOR UPDATE`** | Two users book the last EV slot (`C60`) at the same millisecond → double booking! | `parking-service` locks the user's booking attempt and locks compatible slot rows in `parking_db` inside one transaction so only 1 user wins. |
| **Vehicle Snapshots on `bookings`** | User later edits their car's plate or deactivates it → old booking history shows the wrong car. | `bookings` stores `vehicle_number_snapshot`, `vehicle_type_snapshot`, and `is_ev_snapshot` at booking time. |
| **`X-Internal-Service-Token` + Gateway Stripping** | Anyone on the internet could fake a `POST /internal/v1/bookings/{id}/payment-result` (`SUCCESS`) to get free parking! | Gateway blocks `/internal/*` (`404`) and strips `X-Internal-Service-Token`; services verify per-direction secret tokens internally. |
| **Lazy Hold Expiry** | Need a separate background worker/Cron/Celery process just to flip unpaid 5-min holds to `EXPIRED`. | Availability queries ignore `hold_expires_at <= now()`, and reads/callbacks flip expired holds to `EXPIRED` on access—zero extra daemons! |
