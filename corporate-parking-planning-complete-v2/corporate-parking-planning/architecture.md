# System Architecture

## 1. Architectural style

The system is planned as a small microservice-based backend with four business services and one API Gateway. Each business service owns its business logic and data. Services communicate through defined HTTP APIs; no service directly queries another service's database.

The architecture is intentionally limited to the services justified by current business use cases. It is not intended to maximize the service count.

## 1.1 Agreed service technology baseline

The repository is a monorepo with `services/user-auth-service`, `services/vehicle-service`, `services/parking-service`, `services/payment-service`, and `gateway/`.

- **Business services:** **Python + FastAPI** using synchronous route handlers (`def`) for database operations, **synchronous SQLAlchemy (`Session`)** with the **`psycopg` (v3)** PostgreSQL driver, request-scoped SQLAlchemy sessions via FastAPI dependencies, and **independent Alembic migrations** per service. Avoid mixing synchronous and asynchronous database sessions.
- **Data isolation:** Database engines, session factories, declarative metadata, ORM models, Alembic configurations, and migration histories are owned separately by each service. Never share ORM models or migration histories across services.
- **API Gateway:** Lightweight **FastAPI reverse proxy** (`gateway/`). Infrastructure only (routing, authentication validation, CORS, and request-level concerns); no business logic or database. Never exposes `/internal/v1/*` routes and strips externally supplied internal service authentication headers. Internal service-to-service calls bypass the Gateway.

## 2. Component inventory

| Component | Classification | Owns | Responsibilities |
|---|---|---|---|
| API Gateway | Infrastructure component | No business database | Public frontend entry point, routing and common request handling |
| User/Auth Service | Business microservice | User/Auth data | Corporate email verification, Google OAuth, user identity, access/refresh authentication |
| Vehicle Service | Business microservice | Vehicle data | Register, list, retrieve, update and deactivate user vehicles |
| Parking Service | Business microservice | Slot inventory and bookings | Availability, booking validation, slot allocation, temporary holds, pricing, cancellation and booking history |
| Payment Service | Business microservice | Payment records | Create and simulate payment attempts, expose payment status, report result to Parking |

## 3. High-level component view

```mermaid
flowchart TB
    FE[Frontend] --> GW[API Gateway]
    GW --> UA[User/Auth Service]
    GW --> VS[Vehicle Service]
    GW --> PS[Parking Service]
    GW --> PAY[Payment Service]

    PS <-->|Vehicle lookup| VS
    PS -->|Create payment attempt| PAY
    PAY -->|Payment result callback| PS

    UA --- UDB[(User/Auth database)]
    VS --- VDB[(Vehicle database)]
    PS --- PDB[(Parking database)]
    PAY --- PAYDB[(Payment database)]

    GOOGLE[Google OAuth] <--> UA
    EMAIL[Email provider] <-- UA
```

The Gateway handles frontend ingress. Internal service-to-service calls should use service addresses directly rather than being routed back through the public Gateway.

## 4. Service responsibilities and boundaries

### 4.1 User/Auth Service

**Owns:** user identity, email verification records, authentication identities and refresh sessions.

**Does:**
- validate the configured corporate email domain;
- generate, hash, expire and verify email codes;
- initiate and complete Google OAuth;
- create or resolve an application user identity;
- issue access tokens and manage refresh sessions;
- return the authenticated user's profile.

**Does not:** own vehicles, parking bookings or payment records.

### 4.2 Vehicle Service

**Owns:** registered vehicle information.

**Does:**
- create and list vehicles for the authenticated owner;
- retrieve a vehicle for owner-scoped or authorized internal validation;
- update vehicle details subject to booking-related restrictions;
- deactivate vehicles while preserving references needed for booking history.

**Does not:** allocate parking slots or calculate fees.

### 4.3 Parking Service

**Owns:** parking slot inventory and all booking state.

**Does:**
- validate booking date/time and user-level overlap;
- retrieve authoritative vehicle attributes from Vehicle Service;
- determine compatible slot type;
- calculate availability;
- atomically lock/recheck slot capacity and create a five-minute hold;
- calculate the parking/charging-session fee;
- initiate a payment attempt through Payment Service;
- transition bookings according to payment results, expiry and cancellation;
- provide booking history and details.

**Does not:** own user credentials, vehicle master records or payment transaction records.

### 4.4 Payment Service

**Owns:** payment attempt records and simulated payment outcomes.

**Does:**
- create one payment attempt for a booking using the amount supplied by Parking;
- simulate a payment outcome without trusting a client-supplied status;
- expose the authenticated user's payment details;
- notify Parking of the final result;
- retry undelivered result callbacks safely.

**Does not:** calculate parking fees, allocate slots or directly update the Parking database.

## 5. Why these services exist

- **User/Auth** separates identity and authentication from parking operations.
- **Vehicle** avoids repetitive vehicle entry and gives vehicle records a clear owner.
- **Parking** contains the core capacity, allocation and reservation rules.
- **Payment** isolates payment lifecycle and its failure/retry behavior from booking logic.
- **Gateway** provides one frontend-facing entry point but is not a business microservice.

The Session Service was removed because there is no current check-in/check-out, actual-use billing, overstay or no-show workflow. A separate service would not solve a current business problem.

## 6. Data ownership principle

Each service is the authoritative owner of its own records:

| Data | Authoritative owner |
|---|---|
| User identity and authentication identities | User/Auth Service |
| Verification codes and refresh sessions | User/Auth Service |
| Vehicle registration and EV/type attributes | Vehicle Service |
| Parking slot inventory | Parking Service |
| Booking records, status, amount and hold expiry | Parking Service |
| Payment method, payment status and transaction reference | Payment Service |

Cross-service IDs such as `user_id`, `vehicle_id`, `booking_id` and `payment_id` are logical references. They are not cross-database foreign keys. A service must not directly read or update another service's tables.

## 7. Database topology

**Agreed:** PostgreSQL is the database technology, using **four separately owned PostgreSQL databases** (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) on one local PostgreSQL server for development.

Each service uses separate database credentials/roles with permissions restricted to its own database. Cross-database foreign keys and direct cross-service table access are prohibited. Each service independently manages its own schema via Alembic.

## 8. Main synchronous service interactions

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant GW as API Gateway
    participant P as Parking Service
    participant V as Vehicle Service
    participant PAY as Payment Service
    participant DB as Parking PostgreSQL

    FE->>GW: Create booking + access token
    GW->>P: Forward authenticated request
    P->>V: Validate vehicle and ownership
    V-->>P: Vehicle type, EV and active status
    P->>DB: Validate conflicts; lock candidate; create hold
    DB-->>P: PAYMENT_PENDING booking
    P->>PAY: Create payment attempt
    PAY-->>P: PENDING payment ID
    P-->>GW: Booking and payment details
    GW-->>FE: Payment required
    FE->>GW: Process simulated payment
    GW->>PAY: Process payment
    PAY->>P: Internal payment-result callback
    P->>DB: Confirm or expire booking
    P-->>PAY: Callback acknowledged
```

The exact request/response schemas, authentication headers, timeouts and retry policies are specified in later documents.

## 9. Slot allocation and concurrency boundary

Parking Service is the only service allowed to allocate slots. Availability queries are informational. Booking creation must re-check capacity inside a database transaction so two users cannot claim the same slot for overlapping time intervals.

A row-locking strategy for candidate slots is proposed. Serialization of simultaneous requests from the same user must also be considered to protect the no-overlapping-bookings rule. The exact PostgreSQL locking and constraint strategy will be documented as a technical decision before implementation.

## 10. API Gateway responsibilities

The Gateway is expected to:
- expose the public route prefixes;
- route requests to the owning service;
- perform common ingress handling such as CORS and request correlation;
- validate user access tokens as an early rejection layer, while downstream services also validate identity;
- avoid containing business rules or direct database access.

Internal service endpoints must not be exposed as public Gateway routes.

## 11. External dependencies

| External system | Used by | Reason |
|---|---|---|
| Corporate email provider | User/Auth | Deliver email verification code |
| Google OAuth | User/Auth | Optional identity authentication path |
| Real payment provider | None in current scope | Future integration only |
| Physical parking hardware | None | Explicitly outside current scope |

## 12. Deliberate architectural exclusions

- No Session Service.
- No Admin Service for the seeded sample slot inventory.
- No Notification Service in the current scope.
- No Kafka or RabbitMQ for the present synchronous workflows and callback retry design.
- No shared database access between services.
- No direct service-to-service database writes.
- No separate Hold Service; a hold is represented by a payment-pending booking with an expiry timestamp.

## 13. Architecture status (m0 finalized)

All pre-implementation architecture decisions are finalized for the sprint demo baseline in `decisions-and-open-questions.md`:
- Monorepo + lightweight FastAPI reverse-proxy Gateway (`gateway/`).
- Four separate PostgreSQL databases + synchronous SQLAlchemy (`Session`) + `psycopg` (v3) + independent Alembic per service.
- RS256 JWT (15-min) + 7-day HttpOnly refresh cookie + per-direction `X-Internal-Service-Token` headers.
- Advisory lock + `FOR UPDATE` slot locking, lazy hold expiry, and 2 inline retries for payment create & callback.
