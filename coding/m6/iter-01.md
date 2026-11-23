# Milestone 6 (m6) — Iteration 01: API Gateway (`gateway/`) & Multi-Service Launcher

## Goal
Implement the lightweight FastAPI reverse-proxy **API Gateway** (`gateway/`, port `8000`) as the single public frontend entry point, enforcing early RS256 JWT validation, blocking `/internal/v1/*`, stripping externally supplied `X-Internal-Service-Token` headers, preserving OAuth redirects & refresh cookies, and adding a one-command launcher script (`scripts/start_all.ps1`).

## What Was Built

### 1. API Gateway (`gateway/`)
- `gateway/app/core/security.py` — Validates RS256 access JWTs using `keys/jwt_public.pem` (`iss`, `aud`, `sub`, `iat`, `exp`).
- `gateway/app/main.py` — Lightweight FastAPI reverse proxy (infrastructure only, zero business logic or DB):
  - Routes `/api/v1/auth/*` (public) and `/api/v1/users/*` (JWT required) → `user-auth-service` (`8001`).
  - Routes `/api/v1/vehicles/*` (JWT required) → `vehicle-service` (`8002`).
  - Routes `/api/v1/parking/*` (JWT required) → `parking-service` (`8003`).
  - Routes `/api/v1/payments/*` (JWT required) → `payment-service` (`8004`).
  - Explicitly blocks `/internal/*` with `404 NOT_FOUND`.
  - Strips `X-Internal-Service-Token` and hop-by-hop headers on every request before forwarding.
  - Preserves `302` redirects and `Set-Cookie` headers (`follow_redirects=False`).
  - Echoes `X-Request-ID` and returns `503 SERVICE_UNAVAILABLE` in the standard error envelope if a downstream service is unreachable.

### 2. Local Multi-Service Launcher
- `scripts/start_all.ps1` — Launches all 4 business services (`8001`–`8004`) and the API Gateway (`8000`) in labeled PowerShell windows with one command.

### 3. Automated Tests
- `gateway/tests/test_gateway.py` — Tests `/health`, `/internal/v1/*` blocking, early `401` JWT rejection, valid JWT routing + `X-Internal-Service-Token` stripping, public OAuth `302` + `Set-Cookie` preservation, and `503` downstream failure handling.

## How to Run Locally
```powershell
.\scripts\start_all.ps1
```
Then send all frontend/client requests to **`http://127.0.0.1:8000/api/v1/...`**!
