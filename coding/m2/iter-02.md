# Milestone 2 (m2) — Iteration 02: Drop Google OAuth (Company Email OTP Only)

## Decision
Dropped Google OAuth (`GET /api/v1/auth/google` and `GET /api/v1/auth/google/callback`) because the application exclusively serves company employees; authentication is now purely based on corporate email OTP verification (`COMPANY_EMAIL_DOMAIN`).

## Changes Made
- Deleted `services/user-auth-service/app/services/google_oauth.py`.
- Removed `/api/v1/auth/google`, `/api/v1/auth/google/callback`, and `oauth_state` cookie handling from `services/user-auth-service/app/api/v1/auth.py`.
- Removed `GOOGLE_*` and `FRONTEND_AUTH_*` settings from `app/core/config.py`, `.env.example`, and `.env` (reset `COMPANY_EMAIL_DOMAIN=company.com`).
- Removed `httpx` from `services/user-auth-service/requirements.txt` (no outbound HTTP calls needed in `user-auth-service`).
- Updated `services/user-auth-service/tests/test_auth.py` and `gateway/tests/test_gateway.py`.
- Updated `coding/` docs (`PROGRESS.md`, `API-FLOWS.md`, `API-TESTING-GUIDE.md`, `DEPENDENCIES.md`, `WHY-WE-USE-EACH-TOOL.md`).

## Updated API Count
- **User/Auth Service:** **5 APIs** (`send-code`, `verify`, `users/me`, `refresh`, `logout`)
- **Total System APIs:** **20 APIs** (17 public + 3 internal)
