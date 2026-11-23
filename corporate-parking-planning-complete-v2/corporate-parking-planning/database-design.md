# PostgreSQL Database Design

**Document status:** Finalized sprint-demo relational model. PostgreSQL (four separate databases: `user_db`, `vehicle_db`, `parking_db`, `payment_db`), synchronous SQLAlchemy (`Session`) with `psycopg` (v3), independent Alembic migrations per service, `VARCHAR + CHECK` constraints, partial unique active-vehicle index, and `pg_advisory_xact_lock` + `FOR UPDATE` locking are all agreed.

## 1. Database ownership principle

Each business service owns its data. No service directly queries or updates another service's tables. IDs crossing service boundaries are logical references, not cross-database foreign keys.

| Database owner | Database | Tables |
|---|---|---|
| User/Auth Service | `user_db` | `users`, `auth_identities`, `verification_codes`, `refresh_sessions` |
| Vehicle Service | `vehicle_db` | `vehicles` |
| Parking Service | `parking_db` | `parking_slots`, `bookings`, `booking_idempotency_keys` |
| Payment Service | `payment_db` | `payments` |

**Agreed:** PostgreSQL.

**Agreed topology:** four separately owned PostgreSQL databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) on one local PostgreSQL server for development, with separate database credentials/roles per service and no cross-database foreign keys or direct cross-service table access.

## 2. PostgreSQL conventions

- UUID primary keys for service entities and cross-service identifiers.
- `TIMESTAMPTZ` for event timestamps and expiry instants.
- `DATE` and `TIME WITHOUT TIME ZONE` for parking calendar date and local time boundaries; interpret them under the configured `Asia/Kolkata` business timezone.
- `NUMERIC(10,2)` for monetary amounts; never use floating-point types for money.
- Store normalized email and normalized vehicle registration consistently.
- Add database constraints for uniqueness and simple invariants; retain complex business validation in the owning service.
- Each service owns and runs its own schema migrations using **Alembic** independently (never share migration histories between services).
- Each service owns its own SQLAlchemy declarative metadata, ORM models, database engine, and synchronous `Session` factory (`psycopg` v3). Do not import another service's ORM models.
- UUID generation may occur in the application or with PostgreSQL's UUID generation support; choose one convention and use it consistently.

## 3. User/Auth database

### 3.1 `users`

| Column | Type | Null? | Constraints / meaning |
|---|---|---:|---|
| `id` | UUID | No | Primary key |
| `email` | VARCHAR(255) | No | Normalized corporate email; unique |
| `name` | VARCHAR(100) | Yes | Optional display name; email verification does not provide a name |
| `created_at` | TIMESTAMPTZ | No | Creation time |
| `updated_at` | TIMESTAMPTZ | No | Last update time |

The `auth_identities` table separates provider identities from `users` so corporate-email OTP (`COMPANY_EMAIL`) is cleanly modeled and extensible if additional corporate SSO providers are added later.

### 3.2 `auth_identities`

| Column | Type | Null? | Constraints / meaning |
|---|---|---:|---|
| `id` | UUID | No | Primary key |
| `user_id` | UUID | No | FK to `users.id` in the same database |
| `provider` | VARCHAR(30) | No | `COMPANY_EMAIL` (Google OAuth dropped from scope) |
| `provider_subject` | VARCHAR(255) | No | Stable provider-side subject (normalized corporate email) |
| `provider_email` | VARCHAR(255) | Yes | Verified provider email captured at authentication time |
| `created_at` | TIMESTAMPTZ | No | Creation time |

Constraints/indexes:
- FK `user_id -> users.id`.
- `UNIQUE(provider, provider_subject)`.
- Index `user_id`.
- Validate provider values using a check constraint.

### 3.3 `verification_codes`

| Column | Type | Null? | Constraints / meaning |
|---|---|---:|---|
| `id` | UUID | No | Primary key |
| `email` | VARCHAR(255) | No | Normalized target email |
| `code_hash` | VARCHAR(255) | No | Protected code representation; never plaintext |
| `expires_at` | TIMESTAMPTZ | No | Code expiry instant |
| `attempt_count` | INTEGER | No | Default 0; must be non-negative |
| `consumed_at` | TIMESTAMPTZ | Yes | Set after successful verification |
| `invalidated_at` | TIMESTAMPTZ | Yes | Set when superseded, exhausted, or otherwise invalidated |
| `created_at` | TIMESTAMPTZ | No | Creation time |

Indexes:
- Index `(email, created_at DESC)` to find recent attempts.
- Consider an index supporting active-code lookup by email and expiry.

The service transaction must invalidate the previous active code before creating a replacement. A unique constraint on all rows by email is not appropriate because historical verification attempts may be retained.

**Security note:** a six-digit code has low entropy. Protect the stored value with a server-secret HMAC/pepper or an appropriately slow salted verification approach; an unkeyed fast digest alone is not sufficient protection against an offline database-leak brute-force attempt.

### 3.4 `refresh_sessions`

| Column | Type | Null? | Constraints / meaning |
|---|---|---:|---|
| `id` | UUID | No | Primary key |
| `user_id` | UUID | No | FK to `users.id` |
| `token_hash` | VARCHAR(255) | No | Hash of refresh secret; unique |
| `expires_at` | TIMESTAMPTZ | No | Expiry instant |
| `created_at` | TIMESTAMPTZ | No | Creation time |
| `revoked_at` | TIMESTAMPTZ | Yes | Revocation time; null while usable |

Constraints/indexes:
- FK `user_id -> users.id`.
- Unique `token_hash`.
- Index `user_id`.

The refresh-session table supports the approved short-lived RS256 access JWT + revocable refresh-session model (with `POST /api/v1/auth/refresh`, Secure HttpOnly refresh cookie, and refresh-token rotation).

## 4. Vehicle database

### 4.1 `vehicles`

| Column | Type | Null? | Constraints / meaning |
|---|---|---:|---|
| `id` | UUID | No | Primary key |
| `user_id` | UUID | No | Logical reference to User/Auth `users.id`; no cross-database FK |
| `vehicle_number` | VARCHAR(20) | No | Normalized vehicle registration number |
| `vehicle_type` | VARCHAR(10) | No | `CAR` or `BIKE` |
| `is_ev` | BOOLEAN | No | Whether the registered vehicle is electric |
| `is_active` | BOOLEAN | No | Soft-deactivation state; default true |
| `created_at` | TIMESTAMPTZ | No | Creation time |
| `updated_at` | TIMESTAMPTZ | No | Last update time |

Constraints/indexes:
- Index `user_id` for owner-scoped list/get operations.
- Check `vehicle_type IN ('CAR','BIKE')` (or equivalent controlled enum).
- Recommended: unique partial index on `(user_id, vehicle_number) WHERE is_active = true`, allowing a deactivated vehicle to be registered again while keeping the old record for historical references.

**Open:** confirm whether re-registering a deactivated vehicle creates a new row or reactivates the old row. The partial unique-index proposal assumes a new active row may be created.

## 5. Parking database

### 5.1 `parking_slots`

| Column | Type | Null? | Constraints / meaning |
|---|---|---:|---|
| `id` | UUID | No | Primary key |
| `slot_number` | VARCHAR(10) | No | Unique slot label, e.g. `C01`, `B01` |
| `vehicle_type` | VARCHAR(10) | No | `CAR` or `BIKE` |
| `is_charging_enabled` | BOOLEAN | No | Whether this physical/logical slot supports charging |

Constraints/indexes:
- `UNIQUE(slot_number)`.
- Check vehicle type is `CAR` or `BIKE`.
- Seed the current 100 slots: 50 normal car, 10 charging-enabled car, 35 normal bike, 5 charging-enabled bike.

No `is_occupied`, `is_available`, or `current_booking_id` field is required. Availability is derived from slot inventory plus overlapping active bookings/valid holds. No separate Admin Service is needed to seed this project's fixed sample inventory.

### 5.2 `bookings`

| Column | Type | Null? | Constraints / meaning |
|---|---|---:|---|
| `id` | UUID | No | Primary key |
| `user_id` | UUID | No | Logical reference to User/Auth; no cross-database FK |
| `vehicle_id` | UUID | No | Logical reference to Vehicle Service; no cross-database FK |
| `vehicle_number_snapshot` | VARCHAR(20) | No | Immutable normalized vehicle number captured at booking creation |
| `vehicle_type_snapshot` | VARCHAR(10) | No | Immutable vehicle type (`CAR` or `BIKE`) captured at booking creation |
| `is_ev_snapshot` | BOOLEAN | No | Immutable EV flag captured at booking creation |
| `slot_id` | UUID | No | FK to `parking_slots.id` in the same database |
| `booking_date` | DATE | No | Calendar date in `Asia/Kolkata` |
| `start_time` | TIME WITHOUT TIME ZONE | No | Local start boundary (nominal whole hour, including same-hour exception) |
| `end_time` | TIME WITHOUT TIME ZONE | No | Local end boundary |
| `requires_charging` | BOOLEAN | No | Booking-specific charging choice |
| `status` | VARCHAR(20) or enum | No | `PAYMENT_PENDING`, `CONFIRMED`, `EXPIRED`, `CANCELLED` |
| `amount` | NUMERIC(10,2) | No | Amount calculated by Parking; INR under current scope |
| `hold_expires_at` | TIMESTAMPTZ | Yes | Required while payment pending; hold expiry instant |
| `payment_id` | UUID | Yes | Logical reference to Payment; unique when present |
| `created_at` | TIMESTAMPTZ | No | Creation time |
| `updated_at` | TIMESTAMPTZ | No | Last update time |
| `cancelled_at` | TIMESTAMPTZ | Yes | Set on cancellation |

### 5.2.1 Booking idempotency storage (`booking_idempotency_keys`)

**Agreed:** `POST /api/v1/parking/bookings` requires an `Idempotency-Key` (client-generated UUID), persisted in Parking DB and uniquely scoped to `(user_id, idempotency_key)`:
- Associates the key with a request payload fingerprint/hash and the resulting `booking_id` (FK to `bookings.id`).
- Same user + same key + same payload replays the original booking result.
- Same user + same key + different payload returns `409 Conflict`.
- Prevents network retries from creating duplicate bookings or holds.

Constraints/indexes:
- FK `slot_id -> parking_slots.id`.
- Unique `payment_id` (PostgreSQL permits multiple nulls under a normal unique constraint).
- Check `end_time > start_time`.
- Check `amount >= 0`.
- Check status belongs to the allowed state set.
- Index `(user_id, booking_date)` for owner history and overlap lookups.
- Index `(slot_id, booking_date, status)` for slot-conflict queries.
- Index `hold_expires_at` for finding pending holds that have expired.
- Consider an index on `vehicle_id` for vehicle-dependency checks.

The `slot_id` foreign key is local to Parking DB. The `user_id`, `vehicle_id`, and `payment_id` values are logical references only.

### 5.3 Booking status values

```text
PAYMENT_PENDING
CONFIRMED
EXPIRED
CANCELLED
```

Use a PostgreSQL enum or a `VARCHAR` plus `CHECK` constraint. The exact choice is an implementation/migration decision; avoid accepting arbitrary strings. State transitions are governed by the workflow document.

### 5.4 Concurrency and overlap protection

The application-level booking transaction must prevent:
- two bookings from taking the same slot for overlapping intervals;
- one user from creating overlapping bookings across different slots/vehicles.

The design discussion proposed locking candidate `parking_slots` rows and re-checking conflicts in the same transaction. Concurrent requests for the same user also need serialization (for example, an advisory transaction lock or another reliable strategy).

A PostgreSQL exclusion constraint using range types may be evaluated, but the status/hold-expiry semantics and stale pending rows make the exact constraint non-trivial. Do not claim that a simple unique constraint prevents interval overlap. Final locking/constraint strategy is open until the workflow/concurrency design is completed.

## 6. Payment database

### 6.1 `payments`

| Column | Type | Null? | Constraints / meaning |
|---|---|---:|---|
| `id` | UUID | No | Primary key |
| `booking_id` | UUID | No | Logical reference to Parking booking; unique |
| `user_id` | UUID | No | Logical reference to User; copied from trusted Parking request for ownership checks |
| `amount` | NUMERIC(10,2) | No | Amount received from Parking; not recalculated |
| `payment_method` | VARCHAR(20) | Yes | `UPI`, `CARD`, `WALLET`; null until process request |
| `status` | VARCHAR(20) or enum | No | `PENDING`, `SUCCESS`, `FAILED` |
| `transaction_id` | VARCHAR(100) | Yes | Simulated transaction reference; unique when present |
| `expires_at` | TIMESTAMPTZ | No | Payment expiry aligned with booking hold |
| `created_at` | TIMESTAMPTZ | No | Creation time |
| `updated_at` | TIMESTAMPTZ | No | Last update time |
| `callback_delivered_at` | TIMESTAMPTZ | Yes | When Parking acknowledged result |
| `callback_attempts` | INTEGER | No | Default 0; non-negative |
| `next_callback_at` | TIMESTAMPTZ | Yes | Scheduled next retry time |
| `callback_last_error` | TEXT | Yes | Sanitized diagnostic; must not contain secrets or tokens |

Constraints/indexes:
- `UNIQUE(booking_id)` enforces one payment attempt per booking.
- `UNIQUE(transaction_id)`; multiple nulls are allowed.
- Check `amount > 0`.
- Check callback attempts are non-negative.
- Check allowed payment status and method values.
- Index `(user_id, created_at DESC)` for ownership-scoped payment lookup/history support.
- Index `next_callback_at` for pending callback retry processing.
- Index `expires_at` if expiry reconciliation scans are required.

`booking_id` and `user_id` are not foreign keys to other service databases. Payment Service owns its local payment rows only.

### 6.2 Payment status values

```text
PENDING
SUCCESS
FAILED
```

No refund state is required in the current simulated scope. `SUCCESS` and `FAILED` are terminal for the same payment attempt.

## 7. Relationship summary

```text
USER/AUTH DATABASE
users 1 ─── many auth_identities
users 1 ─── many refresh_sessions
verification_codes are keyed by normalized email (not user FK required before first login)

VEHICLE DATABASE
vehicles.user_id ─── logical User/Auth users.id reference

PARKING DATABASE
parking_slots 1 ─── many bookings
bookings.user_id ─── logical User/Auth users.id reference
bookings.vehicle_id ─── logical Vehicle vehicles.id reference
bookings.payment_id ─── logical Payment payments.id reference

PAYMENT DATABASE
payments.booking_id ─── logical Parking bookings.id reference
payments.user_id ─── logical User/Auth users.id reference
```

Only relationships inside a service's own database use database foreign keys. Cross-service relationships are validated through APIs or trusted workflow contracts.

## 8. Time and timezone policy

- `booking_date`, `start_time`, and `end_time` are local business-calendar values under `Asia/Kolkata`.
- `created_at`, `updated_at`, `cancelled_at`, `hold_expires_at`, `expires_at`, and callback timestamps are `TIMESTAMPTZ` instants.
- API timestamps should include an explicit offset (for example `+05:30`) or use a documented UTC representation.
- Do not store a timezone-naive timestamp for an expiry instant.
- The application must use one consistent business timezone when translating a booking date/time into a start/end instant for cancellation/expiry comparisons.

## 9. Monetary representation

- `NUMERIC(10,2)` is the recommended PostgreSQL amount type.
- Current rates are ₹10/hour for normal parking and ₹20/hour for EV bookings requesting charging.
- The ₹20 rate is the total rate, not an additional ₹20 on top of ₹10.
- Parking calculates the amount; Payment stores the supplied amount.
- **Agreed:** all bookings (including the same-hour exception) store the nominal whole-hour block and charge the full whole-hour rate with no prorating.

## 10. Data retention and deletion

- Booking rows are not deleted through the user API; cancellation is a state transition.
- Payment rows are retained as payment history.
- Vehicle removal is soft deactivation; no physical delete where bookings may reference the vehicle.
- Verification-code retention/cleanup period is not yet decided. Expired/consumed verification records may be purged under a documented retention policy after implementation.
- No cross-service cascade delete is allowed.

## 11. Database credentials and migrations

Recommended deployment practice:
- one database role/credential per service;
- each role has permissions only on its own database (or schema if the single-database topology is selected);
- each service owns its own migrations and does not run another service's migrations;
- no application connection string grants cross-service access.

**Agreed migration tooling:** each service uses **Alembic** independently, maintaining its own Alembic configuration and migration history. Never share migration histories between services, and do not rely on SQLAlchemy `metadata.create_all()` as the production schema-management strategy.

## 12. SQLAlchemy integration design

Synchronous SQLAlchemy (`Session`) with the **`psycopg` (v3)** PostgreSQL driver is the agreed persistence layer between each FastAPI business service and its PostgreSQL database. The following boundaries apply:

- Define ORM models only for tables owned by the current service.
- Keep SQLAlchemy ORM models separate from Pydantic API request/response schemas. Convert between them explicitly in the service/repository layer.
- Create one database engine and synchronous `Session` factory per service process/configuration; do not share a SQLAlchemy session across requests or concurrent threads.
- Provide the request-scoped synchronous `Session` to synchronous FastAPI route handlers (`def`) through a dependency. Ensure it is closed/released after the request.
- Keep transaction boundaries explicit in the business/service layer. Commit successful state changes and roll back on failure. A transaction must not span an HTTP call to another microservice.
- Use SQLAlchemy ORM/Core for normal persistence and allow carefully scoped PostgreSQL-specific statements where required for row locking or advisory locks.
- Keep the synchronous SQLAlchemy + `psycopg` (v3) execution model consistent across all four services; do not mix synchronous and asynchronous database sessions.

## 13. Database decisions (m0 finalized)

All database design decisions are finalized for the sprint demo baseline:
- Four separate PostgreSQL databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) with separate roles/credentials and independent Alembic migrations per service.
- `VARCHAR` + `CHECK` constraints for status/type columns (instead of native PostgreSQL `ENUM`).
- Partial unique index `UNIQUE(user_id, vehicle_number) WHERE is_active = true` so re-registering a deactivated vehicle creates a new active row while preserving history.
- Concurrency: `pg_advisory_xact_lock` per user + `FOR UPDATE` on compatible `parking_slots` ordered by `slot_number ASC` + overlap recheck.
- Lazy hold expiry (no background worker); verification-code retention/purging is deferred.
