# Milestone 0 (m0) — Iteration 01: Planning & Decision Finalization

## Goal
Lock all open architecture, database, API, security, and sprint-demo reliability decisions across the 13 planning documents before writing application code.

## Key Decisions Finalized
1. **Monorepo & Gateway:** `services/user-auth-service`, `services/vehicle-service`, `services/parking-service`, `services/payment-service`, `gateway/` (lightweight FastAPI reverse proxy; blocks `/internal/v1/*`; strips `X-Internal-Service-Token`).
2. **Persistence Stack:** Synchronous SQLAlchemy (`Session`) + `psycopg` (v3) + synchronous FastAPI route handlers (`def`) + independent Alembic migrations per service.
3. **PostgreSQL Topology:** 4 separate databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) with separate roles/credentials and zero cross-DB foreign keys.
4. **22-Operation Baseline:** Approved `POST /api/v1/auth/refresh` (RS256 15-min JWT + 7-day Secure HttpOnly refresh cookie with rotation) and `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` (`409` on blocking bookings).
5. **Booking Rules:** Nominal whole-hour same-hour block (`09:00–10:00` at `09:20`, full 1-hour fee, not cancellable), `Idempotency-Key` header per user, immutable vehicle snapshots (`vehicle_number_snapshot`, `vehicle_type_snapshot`, `is_ev_snapshot`).
6. **Sprint-Demo Simplifications:**
   - Concurrency: `pg_advisory_xact_lock` per user + `SELECT ... FROM parking_slots ORDER BY slot_number ASC FOR UPDATE`.
   - Hold expiry: lazy expiry on availability/read/callback (no background worker).
   - Payment create & callback: up to 2 inline retries (no background polling daemon).
   - Deterministic payment simulation: `PAYMENT_SIMULATION_DEFAULT_OUTCOME=SUCCESS` + non-prod `X-Test-Payment-Outcome` override.
   - Pluggable OTP email sender (console/log mock in dev, never logged in prod) & DB-only OTP abuse limits.
   - Common error envelope: `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`.

## Files Updated
All 13 Markdown files in `corporate-parking-planning-complete-v2/corporate-parking-planning/`.
