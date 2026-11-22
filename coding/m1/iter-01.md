# Milestone 1 (m1) — Iteration 01: Monorepo & Database Foundation

## Goal
Scaffold the monorepo structure (`services/*` + `gateway/`), set up isolated synchronous SQLAlchemy + `psycopg` v3 + Alembic foundations for each business service, add PostgreSQL database/role initialization SQL and RS256 dev key generation, and verify `/health` on all 5 FastAPI apps.

## What Was Built

### 1. Monorepo Layout
- `gateway/` — Lightweight FastAPI reverse-proxy Gateway (`PORT=8000`, no database).
- `services/user-auth-service/` — User/Auth Service (`PORT=8001`, `user_db`).
- `services/vehicle-service/` — Vehicle Service (`PORT=8002`, `vehicle_db`).
- `services/parking-service/` — Parking Service (`PORT=8003`, `parking_db`).
- `services/payment-service/` — Payment Service (`PORT=8004`, `payment_db`).

### 2. Service-Local Persistence & Migration Isolation
Each of the 4 business services independently owns:
- `app/core/config.py` — Pydantic Settings loading its own `.env`.
- `app/core/database.py` — Synchronous SQLAlchemy `create_engine` (`postgresql+psycopg://`), `SessionLocal`, `Base`, and request-scoped `get_db()` generator dependency.
- `app/models/__init__.py` — Service-local ORM model registry (never shared across services).
- `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/` — Independent Alembic migration history wired to the service's own `settings.DATABASE_URL` and `Base.metadata`.

### 3. Common App Conventions (All 5 Apps)
- `GET /health` returning `{"status": "ok", "service": "<service-name>"}`.
- `X-Request-ID` middleware (preserves incoming ID or generates a UUID and echoes it in response headers).
- Standard m0 error envelope (`{ "error": { "code", "message", "request_id" } }`).

### 4. Setup Helper Scripts
- `scripts/init_postgres.sql` — Creates 4 roles (`user_auth_user`, `vehicle_user`, `parking_user`, `payment_user`), 4 databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`), and revokes `PUBLIC` connect permissions to enforce DB isolation.
- `scripts/generate_dev_keys.py` — Generates a 2048-bit RS256 RSA keypair in `keys/` (gitignored).

## How to Run & Verify Locally

1. **Create virtual environment & install dependencies:**
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. **Generate local RS256 dev keys:**
   ```powershell
   python scripts/generate_dev_keys.py
   ```
3. **Initialize the 4 PostgreSQL databases & roles:**
   ```powershell
   psql -U postgres -f scripts/init_postgres.sql
   ```
4. **Run any service or Gateway (example: `user-auth-service`):**
   ```powershell
   uvicorn app.main:app --app-dir services/user-auth-service --port 8001 --reload
   ```
   Then visit `http://127.0.0.1:8001/health`.

## Notes for Next Milestone (m2)
In **m2**, we will build **User/Auth Service** (models, first Alembic migration on `user_db`, and all 7 auth endpoints + tests).
