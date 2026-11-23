# Quality and Testing Plan

**Document status:** Quality baseline and proposed verification plan. Numerical targets are initial project acceptance goals, not measured performance claims.

## 1. Purpose

This document describes expected system quality and how correctness will be verified before deployment. It focuses on the project scope: four business services, the API Gateway, PostgreSQL ownership, booking concurrency and simulated payments.

## 2. Non-functional requirements

| Area | Requirement / target | Status |
|---|---|---|
| Expected scale | Design for approximately 500 employees/users and 100 parking spaces | Agreed sample assumption |
| Normal API latency | Aim for approximately 2 seconds or less for normal requests under expected project load | Initial target; test environment/percentile to be defined |
| Booking correctness | Never allow overlapping active bookings for the same slot | Mandatory correctness requirement |
| User conflict | Never allow the same user to hold/confirm overlapping bookings | Mandatory correctness requirement |
| Access control | Users can access only their own vehicles, bookings and payments | Mandatory security requirement |
| Input validation | Validate request shape, identifiers, date/time, enums, amounts and business rules server-side | Mandatory |
| Service ownership | A service accesses only its own database | Mandatory architectural requirement |
| Service communication | Internal calls use authenticated service identity and defined contracts | Mandatory; exact mechanism open |
| Availability | Availability is informational; booking transaction is authoritative | Agreed |
| Maintainability | Separate API, business logic and persistence responsibilities within each service | Target design |
| Configuration | URLs, credentials, domains, keys, rates where configurable, and secrets outside source code | Mandatory |
| Observability | Basic structured logs, request correlation, health status and safe error reporting | Recommended baseline |
| Documentation | API contracts and service responsibilities remain aligned with implementation | Mandatory handoff requirement |

The two-second target needs a defined measurement point and percentile before it can be treated as a formal performance SLO. Correctness and no-double-allocation take priority over a latency target.

## 3. API validation and error convention

### 3.1 Agreed common error shape

```json
{
  "error": {
    "code": "NO_PARKING_CAPACITY",
    "message": "No compatible parking slot is available for the requested interval.",
    "request_id": "<correlation-id>"
  }
}
```

Adopted consistently across the Gateway and all four business services (`400` malformed syntax/JSON, `422` schema/business-rule validation, `409` state/capacity/overlap/idempotency/blocking-booking conflicts). Do not return stack traces, SQL errors, secrets or internal hostnames to clients.

### 3.2 Proposed HTTP status convention

| Status | Use |
|---:|---|
| `200` | Successful retrieval, state result, or idempotent replay where defined |
| `201` | Resource successfully created |
| `302` | OAuth redirect |
| `400` | Malformed request that cannot be parsed or interpreted |
| `401` | Missing, invalid or expired user/service authentication |
| `403` | Authenticated caller lacks permission for an operation where revealing the resource is acceptable |
| `404` | Resource absent or intentionally concealed because it belongs to another user |
| `409` | Valid request conflicts with current state/capacity or invalid state transition |
| `422` | Request fields are well-formed but fail schema/semantic validation |
| `429` | Rate limit or verification attempt limit exceeded |
| `500` | Unexpected internal error |
| `502` | External email delivery provider failed |
| `503` | Required internal service is unavailable or timed out |

The exact 400/422 mapping should be consistent across services. Existing endpoint documents sometimes group these as `400/422`; the final implementation contract should choose one rule per failure type.

### 3.3 Error code examples

```text
INVALID_REQUEST
INVALID_BOOKING_TIME
BOOKING_WINDOW_VIOLATION
USER_BOOKING_OVERLAP
NO_PARKING_CAPACITY
VEHICLE_NOT_FOUND
VEHICLE_INACTIVE
PAYMENT_EXPIRED
PAYMENT_ALREADY_PROCESSED
BOOKING_NOT_CANCELLABLE
INTERNAL_SERVICE_UNAVAILABLE
INTERNAL_CALLER_UNAUTHORIZED
```

These are examples, not an exhaustive frozen enumeration. Each endpoint document remains authoritative for its resource-specific errors.

## 4. Security and privacy verification

Tests should verify:
- unauthenticated calls to protected endpoints are rejected;
- invalid signature, wrong issuer/audience and expired JWTs are rejected;
- a user cannot list or retrieve another user's vehicles;
- a user cannot view/cancel another user's booking;
- a user cannot process or retrieve another user's payment;
- frontend-supplied `user_id`, `amount`, `slot_id`, `status` or `payment_id` cannot override server-owned values;
- internal endpoints reject calls without valid service authentication;
- internal paths are not routed by the public Gateway;
- Gateway strips client-supplied internal service-auth headers;
- OTP is not returned or logged in production, expires, is one-time and has attempt/cooldown limits;
- secrets and tokens do not appear in logs or error bodies;
- simulated payment never collects real card/UPI secrets.

## 5. Service-level unit tests

### 5.1 User/Auth Service

- valid and invalid email syntax;
- corporate and non-corporate email domain;
- email normalization and case handling;
- OTP hash comparison;
- wrong OTP increments attempts;
- expired OTP rejection;
- old OTP invalidated after resend;
- OTP cannot be reused after successful verification;
- attempt cap and resend cooldown;
- refresh-session revoke and rotation behavior.

### 5.2 Vehicle Service

- create valid CAR and BIKE records;
- reject unsupported vehicle types;
- reject malformed vehicle registration number;
- normalize equivalent registration strings before duplicate check;
- reject duplicate active vehicle for same owner;
- same registration under another owner behavior follows approved uniqueness policy;
- owner-scoped list/get/update/deactivate;
- inactive vehicle cannot be used for a new booking;
- update/deactivation dependency check behavior follows the approved Parking interaction;
- historical booking reference behavior follows the final snapshot/deactivation policy.

### 5.3 Parking Service

- date must be today or tomorrow in `Asia/Kolkata`;
- Sunday closure and Saturday operation;
- operating hours 07:00 to 22:00;
- maximum 12-hour duration and closing boundary;
- more-than-15-minute advance rule, including exact 15-minute rejection;
- same-hour rule at 00–30 minute and after 30 minute boundaries (nominal whole-hour block `09:00–10:00` at `09:20`, full 1-hour fee, not cancellable once confirmed; `10:00–11:00` at `09:35`);
- EV/charging compatibility for both CAR and BIKE;
- charging request on non-EV rejected;
- vehicle must be owned and active;
- booking captures immutable vehicle snapshots (`vehicle_number_snapshot`, `vehicle_type_snapshot`, `is_ev_snapshot`);
- booking creation `Idempotency-Key` replay (same payload returns original booking) and conflict (`409` on different payload);
- user overlap across different vehicles;
- adjacent intervals are allowed;
- slot overlap is rejected;
- cancelled/expired bookings do not block capacity;
- valid pending holds block; expired holds do not;
- fee rates for normal and charging bookings (whole-hour rates, no prorating);
- cancellation at more than five minutes accepted; exactly five minutes rejected;
- only confirmed bookings can be cancelled;
- callback transitions, late callback and duplicate callback behavior;
- history pagination and ownership.

### 5.4 Payment Service

- payment creation validates positive amount and expiry;
- one payment per booking enforced;
- idempotent repeated create with same values returns same payment;
- conflicting duplicate create rejected;
- payment owner validation;
- unsupported payment method rejected;
- client cannot inject payment status;
- payment after expiry rejected;
- payment cannot be processed twice;
- success/failure status persisted before callback attempt;
- callback retry metadata updated correctly;
- duplicate callback acknowledgment does not duplicate Parking state changes.

## 6. API integration tests

Test each public endpoint through the Gateway, including:
- expected success status and response schema;
- required authentication;
- request validation errors;
- ownership checks;
- error propagation from the owning service;
- correct routing to the destination service;
- internal endpoints remain inaccessible through public routing.

## 7. Cross-service integration tests

| Flow | Test scenario | Expected result |
|---|---|---|
| Auth → Vehicle | Valid user token reaches Vehicle | Owner identity is recognized |
| Parking → Vehicle | Existing owned active EV | Parking receives type/EV details |
| Parking → Vehicle | Vehicle belongs to another user | Booking is rejected without leaking vehicle data |
| Parking → Vehicle | Vehicle Service down | Booking fails closed with service-unavailable response |
| Parking → Payment | New booking hold | One pending payment created |
| Parking → Payment | Request retried after response loss | Same payment returned; no duplicate payment |
| Payment → Parking | Successful payment within hold | Booking confirmed |
| Payment → Parking | Failed payment | Booking expired |
| Payment → Parking | Duplicate callback | State remains correct and callback is acknowledged |
| Payment → Parking | Callback delayed past hold expiry | Booking is not resurrected |
| Vehicle → Parking | Dependency lookup (`GET /internal/v1/vehicles/{vehicle_id}/booking-dependency`) | Blocks update/deactivation (`409`) when future/active `CONFIRMED` or valid `PAYMENT_PENDING` booking exists; allows when only historical/`CANCELLED`/`EXPIRED`/ended bookings exist |

## 8. Concurrency tests

These are high-priority tests, not optional polish.

### 8.1 Last compatible slot race

Setup: one compatible slot remains for an interval. Send two simultaneous booking requests from different users.

Expected:
- at most one request receives that slot;
- the other receives another compatible slot if one exists, otherwise `409 NO_PARKING_CAPACITY`;
- no overlapping active booking rows exist for the same slot.

### 8.2 Same-user simultaneous overlap

Setup: one user submits two simultaneous overlapping requests using different vehicles.

Expected: at most one succeeds. The other receives `409 USER_BOOKING_OVERLAP`.

### 8.3 Adjacent intervals

Setup: first booking ends at 10:00; second starts at 10:00.

Expected: both may be allocated, including to the same user, because intervals are half-open and do not overlap.

### 8.4 Hold expiry race

Setup: payment result arrives near or after `hold_expires_at` while expiry cleanup runs.

Expected: row locking/conditional transitions produce one valid terminal outcome. A late success must not resurrect an expired booking.

### 8.5 Duplicate request/callback race

Expected: approved idempotency mechanisms prevent duplicate booking/payment creation and repeated state transitions.

## 9. Time-boundary test matrix

Use a controllable clock in tests rather than depending on real wall-clock timing.

| Rule | Cases to test |
|---|---|
| Booking horizon | Today, tomorrow, day after tomorrow, yesterday |
| Sunday | Sunday as today; Sunday as tomorrow |
| Operating hours | 06:59, 07:00, 21:00, 22:00 end, end after 22:00 |
| Duration | Zero/negative, 1 hour, 12 hours, more than 12 hours |
| Minimum advance | 16 minutes ahead, exactly 15 minutes, 14 minutes |
| Same-hour rule | Minute 00, 29, 30, 31; current-hour block request |
| Cancellation | 6 minutes before, exactly 5 minutes before, 4 minutes before, after start |
| Hold expiry | Just before expiry, exact expiry, just after expiry |

The 09:20 example is agreed: store `start_time = 09:00`, `end_time = 10:00`, charge the full one-hour rate, and reject cancellation once confirmed because `09:00` has already passed. At 09:35, offer `10:00–11:00`.

## 10. Database integrity tests

- primary keys and uniqueness constraints;
- owner-scoped unique vehicle behavior;
- unique payment per booking;
- unique transaction reference when non-null;
- `end_time > start_time`;
- non-negative attempt counters;
- valid vehicle/booking/payment status values;
- positive payment amount;
- same-service foreign keys;
- no cross-database foreign keys;
- no cascade delete from User/Vehicle/Payment into historical bookings.

## 11. Test data and environment expectations

- Use a non-production PostgreSQL database for automated integration tests.
- Seed the Parking DB with the sample 100 slots: 50 normal car, 10 charging-enabled car, 35 normal bike, 5 charging-enabled bike.
- Use deterministic test identities and registered vehicles.
- Provide a controllable clock/test seam for booking and expiry calculations.
- Make simulated payment outcomes deterministic via `PAYMENT_SIMULATION_DEFAULT_OUTCOME` and the non-production-only `X-Test-Payment-Outcome` override header (verify override is disabled in production).
- Reset/rollback test data between cases without sharing production credentials.

## 12. Minimum acceptance criteria before implementation is considered integrated

1. All four services start and connect only to their own PostgreSQL database/schema.
2. Public frontend requests enter through the Gateway.
3. Authentication and owner checks work across all user-owned resources.
4. Vehicle lookup works across the service boundary.
5. Booking creates one temporary hold and one payment attempt.
6. Simulated success confirms a still-valid booking.
7. Simulated failure/timeout expires the booking.
8. Hold expiry releases capacity in availability and cleanup updates state.
9. Cancellation follows the strict five-minute rule.
10. Last-slot and same-user concurrency tests pass.
11. Duplicate payment creation/callback paths are safe.
12. Error responses and logs do not expose secrets or internal traces.

## 13. Items to finalize

- Exact latency measurement (percentile, test load and environment).
- Common error envelope and 400-vs-422 mapping.
- Request/correlation ID format and propagation.
- Final rate-limit thresholds.
- Exact concurrency/transaction mechanism and stress-test load.
- Exact Python test tooling and fixtures for FastAPI/SQLAlchemy integration tests; choose before implementation.
- Test database strategy for transaction, row-locking and concurrency tests (must use PostgreSQL-compatible behavior rather than relying only on SQLite).
