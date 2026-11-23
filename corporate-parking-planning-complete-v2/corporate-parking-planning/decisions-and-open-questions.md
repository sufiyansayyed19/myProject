# Decision Register and Implementation Handoff

**Document status:** Consolidated planning register. This file intentionally distinguishes approved baseline decisions from proposals and blockers. Update it whenever a decision changes.

## 1. How to use this register

Status labels:
- **Agreed** — explicitly settled in planning.
- **Proposed** — recommended, but not yet explicitly approved.
- **Open** — a decision is still needed.
- **Future scope** — intentionally excluded from the current project.

Priority labels:
- **Blocker** — decide before implementing the affected flow.
- **Important** — decide before the relevant feature is complete; scaffolding may proceed without it.
- **Later** — can be decided during implementation or deployment planning without changing the business scope.

Do not change an item from Proposed/Open to Agreed merely because it appears in an example or a technical recommendation.

## 2. Agreed project baseline

| ID | Decision | Status |
|---|---|---|
| A-01 | Product is the Corporate Parking Reservation and Management System | Agreed |
| A-02 | Current business microservices are User/Auth, Vehicle, Parking and Payment | Agreed |
| A-03 | API Gateway is infrastructure, not a business microservice | Agreed |
| A-04 | Session Service is removed; no check-in/check-out, overstay, no-show or actual-use billing | Agreed |
| A-05 | PostgreSQL is the database technology | Agreed |
| A-06 | Expected sample organization has 500 users and 100 spaces | Agreed sample assumption |
| A-07 | 60 car spaces (50 normal, 10 charging-enabled) and 40 bike spaces (35 normal, 5 charging-enabled) | Agreed sample assumption |
| A-08 | Hours 07:00–22:00, Monday–Saturday; Sunday closed; timezone Asia/Kolkata | Agreed |
| A-09 | Booking window is today and tomorrow only; not a rolling seven-day or next-working-days window | Agreed |
| A-10 | Maximum duration 12 hours, and every booking must end by 22:00 | Agreed |
| A-11 | Future whole-hour booking needs strictly more than 15 minutes' notice | Agreed |
| A-12 | Current-hour exception: within first 30 minutes offer nominal whole-hour block (`09:00–10:00` at `09:20`), store `start_time = 09:00`, `end_time = 10:00`, charge full 1-hour rate (no prorating); not cancellable once confirmed because start has passed. After 30 minutes offer next hour (`10:00–11:00` at `09:35`) | Agreed |
| A-13 | Same user cannot have overlapping bookings; adjacent intervals are allowed | Agreed |
| A-14 | User chooses vehicle, not a specific parking slot; Parking auto-allocates | Agreed |
| A-15 | No waitlist | Agreed |
| A-16 | Vehicle types are CAR and BIKE; users can register multiple vehicles | Agreed |
| A-17 | `is_ev` belongs to Vehicle; `requires_charging` belongs to Booking | Agreed |
| A-18 | Non-EV cannot request charging; vehicle type and slot type must match | Agreed |
| A-19 | Normal rate ₹10/hour; EV booking requiring charging ₹20/hour total (all bookings use whole-hour blocks with no prorating) | Agreed |
| A-20 | Availability is informational; create-booking transaction is authoritative | Agreed |
| A-21 | Booking hold is five minutes and is represented by a `PAYMENT_PENDING` booking | Agreed |
| A-22 | Payment success within valid hold confirms booking; failure/timeout/expiry expires it | Agreed |
| A-23 | Late payment success must not resurrect an expired booking | Agreed |
| A-24 | Cancellation only for confirmed booking and strictly more than five minutes before start | Agreed |
| A-25 | Booking is cancelled by state transition, not physical deletion | Agreed |
| A-26 | Booking modification/extension is not supported; cancel and create a new booking | Agreed |
| A-27 | Payment is simulated; no real money/provider integration in current scope | Agreed |
| A-28 | Payment Service does not calculate fees; Parking calculates and supplies amount | Agreed |
| A-29 | One payment attempt per booking; no retry on same booking after failure | Agreed |
| A-30 | Service-owned data; no direct cross-service database access or cross-database foreign keys | Agreed |
| A-31 | No Kafka/RabbitMQ required for current scope | Agreed design constraint |
| A-32 | Physical sensors, RFID, ANPR, actual occupancy detection and kWh billing are excluded | Agreed |
| A-33 | The four business services use Python + FastAPI with synchronous route handlers (`def`) for DB operations | Agreed |
| A-34 | Synchronous SQLAlchemy (`Session`) + `psycopg` (v3) driver + request-scoped sessions via FastAPI dependencies, consistent across all four services (no mixing sync and async DB sessions) | Agreed |
| A-35 | Monorepo layout (`services/user-auth-service`, `services/vehicle-service`, `services/parking-service`, `services/payment-service`, `gateway/`) and lightweight FastAPI reverse-proxy API Gateway (infrastructure only; blocks `/internal/v1/*`; strips externally supplied internal auth headers; internal calls bypass Gateway) | Agreed |
| A-36 | Independent Alembic configuration and migration history per service; never share ORM models or migration histories | Agreed |
| A-37 | Four separately owned PostgreSQL databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) on one local PostgreSQL server with separate credentials/roles per service | Agreed |
| A-38 | Approve `POST /api/v1/auth/refresh` (short-lived RS256 access JWT, Secure HttpOnly refresh cookie, refresh-token rotation, server-side refresh-session validation/revocation) | Agreed |
| A-39 | Approve `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` on Parking Service; Vehicle Service calls it before update/deactivation and rejects with `409 Conflict` if a future/active `CONFIRMED` or valid unexpired `PAYMENT_PENDING` booking exists | Agreed |
| A-40 | Booking creation idempotency via `Idempotency-Key` header (client UUID) on `POST /api/v1/parking/bookings`, persisted per user (`user_id` + `idempotency_key`); identical payload replays original result, differing payload returns `409 Conflict` | Agreed |
| A-41 | Historical vehicle snapshots on `bookings`: `vehicle_number_snapshot`, `vehicle_type_snapshot`, `is_ev_snapshot` alongside logical `vehicle_id` and `requires_charging` | Agreed |
| A-42 | Authentication is purely corporate-email OTP (`COMPANY_EMAIL_DOMAIN`); Google OAuth (`/auth/google`, `/auth/google/callback`) was dropped from scope | Agreed |
| A-43 | Deterministic backend-controlled payment simulation via `PAYMENT_SIMULATION_DEFAULT_OUTCOME=SUCCESS` and non-production-only test override header (e.g., `X-Test-Payment-Outcome: FAILED`); disabled in production; no client-supplied status; no random-only outcomes | Agreed |
| A-44 | Pluggable email OTP sender interface (console/log mock sender in local dev; never expose OTP in API responses; never log OTPs in production; SMTP/provider-ready) | Agreed |

## 3. API inventory baseline

The approved operation count is **20** when both public and internal operations are counted (Google OAuth dropped):

| Service | Operations in baseline | Notes |
|---|---:|---|
| User/Auth | 5 | Company send-code, company verify, users/me, logout, refresh |
| Vehicle | 5 | Create, list, get, update, deactivate |
| Parking | 7 | Five user-facing operations, Payment result callback, and Vehicle booking-dependency check |
| Payment | 3 | Internal payment creation plus two user-facing operations |
| **Total** | **20** | Internal and public operations are both counted |

Route/exposure summary:
- Payment creation is `POST /internal/v1/payments` (internal only; called by Parking Service).
- Payment result callback is `POST /internal/v1/bookings/{booking_id}/payment-result` (internal only; called by Payment Service).
- Vehicle booking dependency check is `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` (internal only; called by Vehicle Service).
- Token refresh is `POST /api/v1/auth/refresh` (public via Gateway).

## 4. Decisions required before implementation (blockers & resolved items)

| ID | Decision | Current position / recommendation | Priority |
|---|---|---|---|
| Q-01 | Language/framework per business service | Resolved: Python + FastAPI (synchronous `def` handlers for DB operations). | Closed |
| Q-02 | API Gateway technology and repository layout | Resolved (A-35): Monorepo (`services/user-auth-service`, `services/vehicle-service`, `services/parking-service`, `services/payment-service`, `gateway/`) with lightweight FastAPI reverse-proxy Gateway. | Closed |
| Q-03 | Same-hour booking exact semantics | Resolved (A-12): Nominal whole-hour block (`09:00–10:00` at `09:20`), store `start_time = 09:00` and `end_time = 10:00`; not cancellable once confirmed because scheduled start has passed; at `09:35` offer `10:00–11:00`. | Closed |
| Q-04 | Partial-hour fee treatment | Resolved (A-12, A-19): Charge full one-hour rate for same-hour bookings; no prorating. | Closed |
| Q-05 | Booking POST idempotency | Resolved (A-40): `Idempotency-Key` (client UUID) header persisted per user in Parking Service; same payload replays original result, different payload returns `409 Conflict`. | Closed |
| Q-06 | PostgreSQL concurrency implementation | Resolved (Sprint Demo Baseline): Single `READ COMMITTED` transaction in `parking_db` using `pg_advisory_xact_lock` on `user_id` + `SELECT ... FROM parking_slots ORDER BY slot_number ASC FOR UPDATE` + overlap recheck + insert. | Closed |
| Q-07 | Expired hold cleanup | Resolved (Sprint Demo Baseline): Lazy expiry — availability/overlap queries ignore `PAYMENT_PENDING` where `hold_expires_at <= now()`, and `GET /bookings`, `GET /bookings/{id}`, or payment callbacks transition expired holds to `EXPIRED` on access (no background worker). | Closed |
| Q-08 | Payment create failure after hold commit | Resolved (Sprint Demo Baseline): Up to 2 inline attempts (3s timeout) using the same `booking_id`; if still unavailable, return `503 PAYMENT_SERVICE_UNAVAILABLE` (hold naturally expires in 5 min). | Closed |
| Q-09 | Payment ID write-back failure | Resolved (Sprint Demo Baseline): Rely on Payment Service idempotency by `booking_id` on retry; no background reconciliation daemon in sprint demo scope. | Closed |
| Q-10 | Vehicle dependency check | Resolved (A-39): Approved `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` on Parking Service; blocks on future/active `CONFIRMED` or valid unexpired `PAYMENT_PENDING` bookings (`409 Conflict`). | Closed |
| Q-11 | Historical vehicle data | Resolved (A-41): Store immutable `vehicle_number_snapshot`, `vehicle_type_snapshot`, and `is_ev_snapshot` on `bookings` alongside `vehicle_id`. | Closed |
| Q-12 | Auth refresh endpoint | Resolved (A-38): Approved `POST /api/v1/auth/refresh` with short-lived RS256 access JWT, Secure HttpOnly refresh cookie, rotation, and server-side revocation. | Closed |
| Q-13 | Account linking / Google OAuth | Closed (A-42): Google OAuth dropped from scope; authentication is purely corporate-email OTP based. | Closed |
| Q-14 | JWT & refresh details | Resolved (Sprint Demo Baseline): RS256 access JWT (15-min lifetime; claims `iss`, `aud`, `sub`, `iat`, `exp`); opaque 7-day refresh token hashed in `refresh_sessions`, rotated on `/auth/refresh`; dev RSA keypair generated via local script and loaded from env. | Closed |
| Q-15 | Internal service authentication | Resolved (Sprint Demo Baseline): Standard header `X-Internal-Service-Token` with per-direction env tokens (`PARKING_TO_VEHICLE_TOKEN`, `PARKING_TO_PAYMENT_TOKEN`, `PAYMENT_TO_PARKING_TOKEN`, `VEHICLE_TO_PARKING_TOKEN`). `Parking -> Vehicle` forwards user `Authorization: Bearer <jwt>` + `X-Internal-Service-Token`. Gateway strips `X-Internal-Service-Token` and blocks `/internal/v1/*`. | Closed |
| Q-16 | Database topology | Resolved (A-37): Four separate PostgreSQL databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) with separate credentials/roles per service. | Closed |
| Q-17 | Slot selection order | Resolved (Sprint Demo Baseline): Deterministic ascending `slot_number` (`C01..C60`, `B01..B40`). | Closed |
| Q-18 | Payment simulation outcome | Resolved (A-43): Deterministic backend-controlled outcome via `PAYMENT_SIMULATION_DEFAULT_OUTCOME=SUCCESS` and non-production-only `X-Test-Payment-Outcome` test override header. | Closed |
| Q-19 | Callback retry policy | Resolved (Sprint Demo Baseline): Persist `SUCCESS`/`FAILED` first, then immediately call Parking callback with up to 2 inline retries (0.5s pause) and record `callback_delivered_at`, `callback_attempts`, and `callback_last_error` in DB (no background polling daemon). | Closed |
| Q-20 | Repeated payment process request | Resolved (Sprint Demo Baseline): Return `409 PAYMENT_ALREADY_PROCESSED`. | Closed |
| Q-21 | Duplicate registration after vehicle deactivation | Resolved (Sprint Demo Baseline): Allow creating a new active row enforced by partial unique index `UNIQUE(user_id, vehicle_number) WHERE is_active = true`. | Closed |
| Q-22 | Common API error envelope | Resolved (Sprint Demo Baseline): `{ "error": { "code": "...", "message": "...", "request_id": "..." } }` across Gateway and all 4 services (`400` malformed syntax, `422` validation, `409` conflicts). | Closed |

## 5. Important decisions finalized for sprint demo

| ID | Decision | Current position | Priority |
|---|---|---|---|
| Q-23 | Four DBs migration mechanics | Resolved (A-36, A-37): Independent Alembic configuration and migration history per service against its own database | Closed |
| Q-24 | PostgreSQL enum vs VARCHAR + CHECK | Resolved (Sprint Demo Baseline): Use `VARCHAR` + `CHECK` constraints for cleaner Alembic migrations | Closed |
| Q-25 | OTP rate limits and resend cooldown | Resolved (Sprint Demo Baseline): DB-based checks only (no Redis) — 5-min expiry, max 5 failed attempts, 60s resend cooldown (env-configurable) | Closed |
| Q-26 | Verification-code retention | Deferred / optional manual cleanup (not required for sprint demo) | Later |
| Q-27 | Pagination envelope/default/max | Resolved (Sprint Demo Baseline): `page=1`, `page_size=20` (max `100`) on booking list | Closed |
| Q-28 | Request/correlation ID convention | Resolved (Sprint Demo Baseline): `X-Request-ID` generated/forwarded by Gateway and returned in error responses | Closed |
| Q-29 | Health/readiness endpoint | Resolved (Sprint Demo Baseline): `GET /health` on Gateway and all four business services | Closed |
| Q-30 | Logging fields/retention | Structured console logs with request ID, service name, route, and sanitized errors (never log OTPs, tokens, or secrets) | Later |
| Q-31 | Performance measurement | Informational ~2s target for demo; formal load testing deferred | Later |
| Q-32 | CORS frontend origins | Env-configured on Gateway (`CORS_ALLOW_ORIGINS`) | Later |
| Q-33 | Service URL/config naming | Env-configured service URLs per service/Gateway | Closed |
| Q-34 | SQLAlchemy execution mode | Resolved (A-34): Synchronous SQLAlchemy `Session` + `psycopg` (v3) + synchronous FastAPI handlers (`def`) across all four services | Closed |
| Q-35 | Migration tooling | Resolved (A-36): Independent Alembic per service | Closed |

## 6. Future scope — not current implementation requirements

- Real payment gateway or sandbox provider integration.
- Provider webhooks, real refunds, settlement, chargebacks and financial reconciliation.
- Notification Service.
- Admin Service/dashboard and dynamic slot administration.
- Visitor parking.
- RFID, IoT sensors, ANPR and physical occupancy automation.
- Waitlist.
- No-show penalties.
- Monthly subscription.
- kWh/dynamic charging billing.
- Department-based parking priorities.
- Advanced analytics.
- User-selected individual parking slot.
- Session/check-in/check-out service and actual-use billing.
- Kubernetes/AWS/CI-CD design is a later DevOps phase, not part of this current planning-to-implementation handoff.

## 7. Implementation handoff — recommended order

The separate implementation conversation/IDE should first read all planning files, then resolve the remaining blocker decisions relevant to the agreed Python/FastAPI/SQLAlchemy/PostgreSQL stack. A reasonable implementation sequence is:

1. **Stack and repository setup:** scaffold the monorepo (`services/user-auth-service`, `services/vehicle-service`, `services/parking-service`, `services/payment-service`, `gateway/`) using synchronous SQLAlchemy (`Session`) + `psycopg` (v3), independent Alembic per service, four PostgreSQL databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`), and the lightweight FastAPI reverse-proxy Gateway.
2. **Database foundations:** create migrations for User/Auth, Vehicle, Parking and Payment storage; seed the 100 parking slots.
3. **Authentication foundation:** user identity, email verification, OAuth if selected, access/refresh lifecycle, JWT validation and service identity.
4. **Vehicle Service:** owner-scoped vehicle CRUD/deactivation and the approved booking-dependency policy.
5. **Parking read paths:** availability and booking history/detail.
6. **Parking booking core:** time/price rules, user-overlap protection, slot row locking, idempotency, five-minute hold and expiry cleanup.
7. **Payment Service:** internal payment creation, simulated processing, payment ownership and callback retry worker.
8. **Cross-service integration:** Vehicle lookup, payment creation and callback; failure handling and request correlation.
9. **Cancellation and complete state lifecycle:** cancellation lock/cutoff, expiry and history.
10. **Automated tests:** unit, API, integration, boundary and concurrency tests listed in `quality-and-testing-plan.md`.

Do not start Docker/Kubernetes/Jenkins/AWS design merely because service implementation is complete. That is a separate phase after local integration and tests work.

## 8. Milestone 0 status

All pre-implementation blockers (`Q-01` through `Q-25`, `Q-27`–`Q-29`, `Q-33`–`Q-35`) are now **Closed** for the sprint demonstration baseline. Only non-blocking operational polish items (`Q-26`, `Q-30`, `Q-31`, `Q-32`) remain deferred to deployment/later phases.

## 9. Change log

| Version | Change |
|---|---|
| Planning Iteration 1 | Established project overview, business-rule baseline and four-service architecture |
| Planning Iteration 2 | Added API contracts and PostgreSQL data model; identified refresh endpoint, vehicle dependency check, historical snapshot and callback/concurrency decisions |
| Planning Iteration 3 | Added service communication/security, end-to-end workflow/reliability, quality/testing and consolidated decision register |
| Stack decision update | Selected Python + FastAPI + SQLAlchemy for the four business services; recorded SQLAlchemy sync/async mode and migration tool as open decisions |
| Decision approval update | Approved monorepo + FastAPI Gateway, synchronous SQLAlchemy (`Session`) + `psycopg` v3, independent Alembic per service, 4 PostgreSQL DBs, nominal whole-hour same-hour booking/billing, `POST /api/v1/auth/refresh` (RS256 + Secure HttpOnly refresh cookie + rotation), `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` (22-operation baseline), `Idempotency-Key` on booking create, historical vehicle snapshots, verified automatic account linking, deterministic backend-controlled payment simulation, pluggable OTP email sender, and env-based Google OAuth config |
| Milestone 0 (m0) sprint-demo finalization | Closed all remaining blockers (`Q-06`–`Q-09`, `Q-14`, `Q-15`, `Q-17`, `Q-19`–`Q-22`, `Q-24`, `Q-25`, `Q-27`–`Q-29`, `Q-33`): advisory lock + `FOR UPDATE` slot locking, lazy hold expiry (no background worker), 2 inline retries for payment create & callback (no background retry worker), RS256 15-min JWT + 7-day refresh cookie, `X-Internal-Service-Token` per-direction tokens, standard error envelope, `VARCHAR + CHECK`, partial unique index for active vehicles, DB-only OTP checks, `X-Request-ID`, and `GET /health` |
| Auth scope simplification (m2 iter-02) | Dropped Google OAuth (`/api/v1/auth/google`, `/api/v1/auth/google/callback`) — authentication is purely corporate-email OTP (`COMPANY_EMAIL_DOMAIN`); total API baseline updated from 22 to 20 (17 public + 3 internal) |
