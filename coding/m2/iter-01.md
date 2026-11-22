# Milestone 2 (m2) — Iteration 01: User/Auth Service (7 APIs)

## Goal
Implement the complete **User/Auth Service** (`services/user-auth-service/`, port `8001`, `user_db`): ORM models, initial Alembic migration, pluggable console OTP email sender, Google OAuth + verified account linking, RS256 access JWT + Secure HttpOnly refresh cookie with rotation, and automated tests.

## Files Created / Updated

| File | Purpose |
|---|---|
| `services/user-auth-service/app/models/auth.py` | 4 SQLAlchemy models: `User`, `AuthIdentity`, `VerificationCode`, `RefreshSession` (with `VARCHAR + CHECK` constraints and indexes) |
| `services/user-auth-service/alembic/versions/0001_initial_auth_tables.py` | Initial Alembic migration creating all 4 tables in `user_db` |
| `services/user-auth-service/app/core/errors.py` | Common m0 error envelope (`{ "error": { "code", "message", "request_id" } }`) for `APIError`, `422`, and `500` |
| `services/user-auth-service/app/core/security.py` | Email normalization, corporate domain check, 6-digit OTP + HMAC-SHA256 verification, RS256 JWT mint/decode, SHA-256 refresh token hashing |
| `services/user-auth-service/app/services/email_sender.py` | Pluggable `EmailSender` protocol + `ConsoleEmailSender` (dev only; blocks logging OTPs in production) |
| `services/user-auth-service/app/services/google_oauth.py` | Google OAuth authorize URL builder + server-to-server code/userinfo exchange |
| `services/user-auth-service/app/schemas/auth.py` | Pydantic request/response schemas (separate from ORM models) |
| `services/user-auth-service/app/api/v1/auth.py` | All 7 synchronous (`def`) endpoints |
| `services/user-auth-service/app/main.py` | Registers error handlers and mounts the `/api/v1` auth router |
| `services/user-auth-service/tests/test_auth.py` | Unit & API tests for all 7 endpoints, abuse controls, token rotation, and verified Google account linking |

## Endpoints Implemented (7 / 7)
1. `POST /api/v1/auth/company/send-code` — Domain check, DB cooldown (`429`), invalidates old codes, stores HMAC hash, sends via pluggable sender.
2. `POST /api/v1/auth/company/verify` — Verifies HMAC hash, expiry, max 5 attempts, consumes code, creates/resolves user, issues RS256 JWT + HttpOnly refresh cookie.
3. `GET /api/v1/auth/google` — Generates OAuth `state` cookie and redirects `302` to Google.
4. `GET /api/v1/auth/google/callback` — Validates `state`, exchanges code, enforces `email_verified = true` + corporate domain, auto-links to existing `User` if verified corporate email matches.
5. `GET /api/v1/users/me` — Validates `Authorization: Bearer <jwt>` with RS256 public key and returns `{id, email, name}`.
6. `POST /api/v1/auth/refresh` — Validates refresh cookie, revokes old `RefreshSession`, issues new rotated refresh cookie + new RS256 access JWT.
7. `POST /api/v1/auth/logout` — Idempotently revokes refresh session and clears cookie.

## How to Run & Test Locally

1. **Apply migration to `user_db`:**
   ```powershell
   Push-Location services\user-auth-service
   ..\..\.venv\Scripts\alembic.exe upgrade head
   Pop-Location
   ```
2. **Run automated tests:**
   ```powershell
   .\.venv\Scripts\pytest.exe services/user-auth-service/tests -v
   ```
3. **Run the service & try Swagger UI (`http://127.0.0.1:8001/docs`):**
   ```powershell
   .\.venv\Scripts\uvicorn.exe app.main:app --app-dir services/user-auth-service --port 8001 --reload
   ```
   - Call `POST /api/v1/auth/company/send-code` with `{"email": "you@company.com"}` — copy the 6-digit code printed in your terminal (`[DEV EMAIL] ...`).
   - Call `POST /api/v1/auth/company/verify` with that email & code to receive your RS256 `access_token`.
   - Authorize in Swagger with `Bearer <access_token>` and call `GET /api/v1/users/me`.
