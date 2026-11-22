# Milestone 2 (m2) — Iteration 01: User/Auth Service (7 APIs)

## Goal
Implement the complete **User/Auth Service** (`services/user-auth-service/`, port `8001`, DB `user_db`) with its 4 PostgreSQL tables, first Alembic migration, pluggable email OTP sender, Google OAuth with verified automatic account linking, RS256 access JWT + rotated HttpOnly refresh cookie, and automated tests.

## What Was Built

### 1. ORM Models & Alembic Migration
- `app/models/auth.py` — 4 SQLAlchemy 2.0 models:
  - `users` (`id`, `email`, `name`, `created_at`, `updated_at`)
  - `auth_identities` (`id`, `user_id`, `provider` CHECK `COMPANY_EMAIL`/`GOOGLE`, `provider_subject`, `provider_email`, `created_at`, `UNIQUE(provider, provider_subject)`)
  - `verification_codes` (`id`, `email`, `code_hash`, `expires_at`, `attempt_count` CHECK `>= 0`, `consumed_at`, `invalidated_at`, `created_at`)
  - `refresh_sessions` (`id`, `user_id`, `token_hash` unique, `expires_at`, `created_at`, `revoked_at`)
- `alembic/versions/0001_initial_auth_tables.py` — First migration creating all 4 tables, constraints, and indexes in `user_db`.

### 2. Security, Error Handling & Pluggable Providers
- `app/core/errors.py` — `AppError` + FastAPI exception handlers returning `{ "error": { "code", "message", "request_id" } }`.
- `app/core/security.py` — Email normalization, corporate domain validation, 6-digit CSPRNG OTP, HMAC-SHA256 OTP hashing, RS256 JWT minting/verification (15-min expiry), SHA-256 refresh-token hashing, and `get_current_user` dependency.
- `app/services/email_sender.py` — `EmailSender` interface + `ConsoleEmailSender` (dev only; blocks logging OTPs in production).
- `app/services/google_oauth.py` — Env-configured Google OAuth URL builder & server-to-server code exchange via `httpx`.

### 3. All 7 API Endpoints (`app/api/v1/auth.py`)
1. `POST /api/v1/auth/company/send-code` — Corporate domain check, 60s DB resend cooldown, invalidates previous active OTPs, stores HMAC hash, sends via `EmailSender`.
2. `POST /api/v1/auth/company/verify` — Validates OTP hash/expiry/attempts (max 5), consumes OTP, creates/finds `User` + `COMPANY_EMAIL` identity, returns RS256 access JWT + sets HttpOnly `refresh_token` cookie.
3. `GET /api/v1/auth/google` — Generates random `state` cookie and redirects `302` to Google.
4. `GET /api/v1/auth/google/callback` — Validates `state`, exchanges `code`, requires `email_verified = true` + corporate domain, auto-links matching verified corporate email to existing `users` row, sets refresh cookie, redirects `302` to frontend.
5. `GET /api/v1/users/me` — Validates Bearer RS256 JWT and returns `{ id, email, name }`.
6. `POST /api/v1/auth/refresh` — Validates refresh cookie, revokes old session, issues rotated refresh cookie + new RS256 access JWT.
7. `POST /api/v1/auth/logout` — Idempotently revokes active refresh session and clears cookie.

### 4. Automated Tests
- `services/user-auth-service/tests/test_auth.py` — Covers all 7 endpoints, corporate domain rejection, resend cooldown, OTP attempt exhaustion, refresh rotation + replay rejection, logout, Google OAuth state validation, unverified rejection, and automatic account linking.

## How to Run & Test Locally

1. **Apply Alembic migration to `user_db`** (after `psql -U postgres -f scripts/init_postgres.sql`):
   ```powershell
   cd services/user-auth-service
   alembic upgrade head
   ```
2. **Start User/Auth Service:**
   ```powershell
   uvicorn app.main:app --app-dir services/user-auth-service --port 8001 --reload
   ```
   Open Swagger UI at `http://127.0.0.1:8001/docs` — call `POST /api/v1/auth/company/send-code` with `{"email": "you@company.com"}`, copy the 6-digit OTP printed in the terminal, and call `POST /api/v1/auth/company/verify`!
3. **Run automated tests:**
   ```powershell
   .venv\Scripts\pytest.exe services/user-auth-service/tests/test_auth.py -v
   ```
