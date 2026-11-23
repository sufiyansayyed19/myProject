# Python Dependencies (`pip` Packages) Guide

Overview of every Python package installed in [requirements.txt](../requirements.txt) and each service's own `requirements.txt` — what it does, **why we chose it**, and where it is used in this project.

---

## 1. Complete Package Reference

| Package | Category | What It Is For | Why We Chose It | Used In |
|---|---|---|---|---|
| **`fastapi`** | Web Framework | Defines HTTP APIs, path/query/header parsing, dependency injection (`Depends`), OpenAPI/Swagger UI (`/docs`), and exception handlers. | Agreed project baseline; fast, clean type-annotated Python, built-in Swagger UI for demos, and native Pydantic validation. | Gateway + all 4 services |
| **`uvicorn[standard]`** | ASGI Server | Runs the FastAPI apps locally on ports `8000`–`8004` with auto-reload (`--reload`). | Standard lightweight server for FastAPI. The `[standard]` extra includes `watchfiles` (fast file reloading) and optimized HTTP handling. | Gateway + all 4 services |
| **`sqlalchemy`** (`>=2.0`) | ORM & DB Access | Maps Python classes (`User`, `Vehicle`, `ParkingSlot`, `Booking`, `Payment`) to PostgreSQL tables, manages connection pools (`create_engine`), transactions (`Session`), and row locking (`.with_for_update()`). | Agreed project baseline; modern SQLAlchemy 2.0 typed syntax (`Mapped`, `mapped_column`), synchronous `Session` per our m0 decision, and clean raw SQL support for `pg_advisory_xact_lock`. | All 4 business services *(not Gateway)* |
| **`psycopg[binary]`** (`>=3.2`) | PostgreSQL Driver | Low-level database driver that lets SQLAlchemy talk to PostgreSQL (`postgresql+psycopg://...`). | Modern **psycopg v3** (the official successor to `psycopg2`). The `[binary]` extra ships precompiled binaries so it installs cleanly on Windows without needing C build tools. | All 4 business services *(not Gateway)* |
| **`alembic`** | Schema Migrations | Tracks and applies versioned database schema changes (`alembic upgrade head`) independently for each service (`user_db`, `vehicle_db`, `parking_db`, `payment_db`). | Official migration tool built for SQLAlchemy; lets each microservice own its own isolated migration history instead of using `create_all()`. | All 4 business services *(not Gateway)* |
| **`pydantic`** (`>=2.7`) | Data Validation | Validates and serializes API request/response schemas (e.g., `VehicleCreate`, `BookingCreateRequest`, `PaymentProcessRequest`) separately from SQLAlchemy ORM models. | Built into FastAPI; enforces strict types, enums (`Literal["CAR", "BIKE"]`), UUIDs, decimals, and custom validators (like vehicle-plate normalization). | Gateway + all 4 services |
| **`pydantic-settings`** | Configuration | Loads environment variables and `.env` files into strongly typed `Settings` classes (`app/core/config.py`). | Keeps secrets, DB URLs, JWT paths, and service URLs out of source code with clean defaults and validation at startup. | Gateway + all 4 services |
| **`email-validator`** | Input Validation | Validates email syntax when using Pydantic's `EmailStr` field type (e.g., `SendCodeRequest`, `VerifyCodeRequest`). | Required by Pydantic v2 whenever `EmailStr` is used; rejects malformed emails before hitting business logic or DB. | `user-auth-service` |
| **`httpx`** | HTTP Client | Makes outbound HTTP calls: Gateway reverse-proxying (`AsyncClient`), `Parking → Vehicle`, `Parking → Payment`, `Payment → Parking`, and `Vehicle → Parking` (`Client`). | Modern replacement for `requests` with both sync (`Client`) and async (`AsyncClient`) APIs, clean timeouts, and `MockTransport` for tests. Also required by FastAPI's `TestClient`. | Gateway, Vehicle, Parking, Payment |
| **`PyJWT[crypto]`** | JWT Auth | Signs RS256 access tokens in `user-auth-service` using `jwt_private.pem` and verifies them locally in Gateway + Vehicle + Parking + Payment using `jwt_public.pem`. | Minimal, standard JWT library. The `[crypto]` extra enables asymmetric **RS256** signing/verification so only `user-auth-service` can mint tokens while other services only hold the public key. | Gateway + all 4 services |
| **`cryptography`** | Cryptography | Used by `scripts/generate_dev_keys.py` to generate the 2048-bit RSA keypair (`keys/jwt_private.pem` and `keys/jwt_public.pem`) and by `PyJWT[crypto]` for RS256 operations. | Industry-standard Python crypto library; eliminates needing external `openssl` installed on Windows to generate dev RSA keys. | `scripts/generate_dev_keys.py`, `user-auth-service` (and transitively via `PyJWT[crypto]`) |
| **`pytest`** | Testing | Runs all unit, API, Gateway, real PostgreSQL concurrency (`test_pg_concurrency.py`), and live 5-app E2E (`test_e2e_journey.py`) test suites. | Standard Python test runner with clean fixtures (`@pytest.fixture`) and FastAPI `dependency_overrides` support. | Dev / Tests (`scripts/run_all_tests.ps1`) |

---

## 2. Service-by-Service Dependency Matrix

| Package | Gateway (`:8000`) | User/Auth (`:8001`) | Vehicle (`:8002`) | Parking (`:8003`) | Payment (`:8004`) |
|---|:---:|:---:|:---:|:---:|:---:|
| `fastapi` | Yes | Yes | Yes | Yes | Yes |
| `uvicorn[standard]` | Yes | Yes | Yes | Yes | Yes |
| `pydantic` & `pydantic-settings` | Yes | Yes | Yes | Yes | Yes |
| `httpx` | Yes | No | Yes | Yes | Yes |
| `PyJWT[crypto]` | Yes | Yes | Yes | Yes | Yes |
| `sqlalchemy` | **No** | Yes | Yes | Yes | Yes |
| `psycopg[binary]` | **No** | Yes | Yes | Yes | Yes |
| `alembic` | **No** | Yes | Yes | Yes | Yes |
| `email-validator` | No | Yes | No | No | No |
| `cryptography` | *(via PyJWT)* | Yes | *(via PyJWT)* | *(via PyJWT)* | *(via PyJWT)* |

> **Why Gateway has no `sqlalchemy`, `psycopg`, or `alembic`:** By architectural rule, the API Gateway is infrastructure-only and owns **no database**—keeping DB packages out of `gateway/requirements.txt` enforces that boundary.

---

## 3. Notable Intentional Omissions (What We Did *Not* Install)

- **No `asyncpg`:** We chose synchronous SQLAlchemy (`Session`) + `psycopg` v3 + `def` FastAPI handlers across all 4 services for simplicity and consistency (`A-34`).
- **No `redis` / `celery` / `kafka-python` / `pika`:** Intentionally excluded in our sprint-demo baseline (OTP cooldowns use PostgreSQL, hold expiry is lazy, and payment callbacks use 2 inline retries).
- **No `stripe` / `razorpay`:** Payment is a deterministic backend-controlled simulation (`A-27`, `A-43`); real payment gateways are future scope.
