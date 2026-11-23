# Service Communication and Security Design

**Document status:** Planning design. Agreed architectural boundaries are separated from recommendations that still need approval.

## 1. Purpose

This document defines how the Gateway, four business services, and their databases communicate. It covers identity propagation, internal service authentication, route exposure, and the minimum security controls required for the current project.

The four business services' stack is agreed as Python + FastAPI + synchronous SQLAlchemy (`Session`) + `psycopg` (v3) + Alembic + PostgreSQL (four separate databases). The API Gateway is agreed as a lightweight FastAPI reverse proxy (`gateway/`). This document does not select a production secret manager or identity platform.

**Database boundary:** SQLAlchemy is used only against the calling service's own PostgreSQL data. Service-to-service communication remains HTTP API communication; ORM models, SQLAlchemy sessions and database connections are never shared across services.

## 2. Components and ownership

| Component | Publicly reachable by frontend? | Owns data? | Primary role |
|---|---:|---:|---|
| API Gateway | Yes | No | Public ingress, routing, CORS and request-level concerns |
| User/Auth Service | Through Gateway | Yes | User identities, corporate-email OTP verification and token/session lifecycle |
| Vehicle Service | Through Gateway | Yes | Registered vehicle records |
| Parking Service | Through Gateway | Yes | Slots, availability, bookings, holds and booking status |
| Payment Service | Through Gateway | Yes | Simulated payment records and callback delivery state |

Internal routes are not exposed through the Gateway.

## 3. Public route map

| Public route prefix | Owning service |
|---|---|
| `/api/v1/auth/*` | User/Auth Service |
| `/api/v1/users/*` | User/Auth Service |
| `/api/v1/vehicles/*` | Vehicle Service |
| `/api/v1/parking/*` | Parking Service |
| `/api/v1/payments/*` | Payment Service |

The Gateway must not expose `/internal/v1/*` routes.

## 4. Service-to-service interaction inventory

| Caller | Destination | Operation | Purpose | Authentication context |
|---|---|---|---|---|
| Parking | Vehicle | `GET /api/v1/vehicles/{vehicle_id}` | Validate vehicle existence, ownership, active state, type and EV property | User identity plus trusted Parking-service identity; exact mechanism open |
| Parking | Payment | `POST /internal/v1/payments` | Create one payment attempt for a committed booking hold | Trusted Parking-service identity |
| Payment | Parking | `POST /internal/v1/bookings/{booking_id}/payment-result` | Report final simulated payment result | Trusted Payment-service identity |
| Vehicle | Parking | `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` | Check whether a vehicle has a blocking booking before changing/deactivating it | Approved internal call; trusted Vehicle-service identity (exact mechanism open) |

No service connects to another service's database. A service-to-service call always crosses the owning service's API boundary.

## 5. Parking-to-Vehicle contract

### Request

```http
GET /api/v1/vehicles/{vehicle_id}
Authorization: Bearer <user-access-token>
<service-authentication-header>: <parking-service-credential>
```

The endpoint is owner-scoped. Vehicle Service should validate that the vehicle belongs to the user represented by the authenticated token and is active when used for a new booking.

### Response

```json
{
  "id": "<vehicle-uuid>",
  "vehicle_number": "MH12AB1234",
  "vehicle_type": "CAR",
  "is_ev": true,
  "is_active": true
}
```

Parking Service uses the response only for the current validation/allocation operation. It does not store a second authoritative vehicle master record.

### Failure handling

- Vehicle not found or not owned by caller: Parking returns `404 VEHICLE_NOT_FOUND` to avoid revealing another user's vehicle.
- Vehicle inactive: reject booking; a specific conflict/not-found response code remains to be aligned in the API contract.
- Vehicle Service unavailable or timeout: fail closed; do not create a booking using unverified/cached vehicle details. Return `503 VEHICLE_SERVICE_UNAVAILABLE`.
- Invalid or incomplete response: treat as an upstream contract failure, log a correlation ID, and return a safe `503` response.

## 6. Parking-to-Payment contract

### Request

```http
POST /internal/v1/payments
Content-Type: application/json
```

```json
{
  "booking_id": "<booking-uuid>",
  "user_id": "<authenticated-user-uuid>",
  "amount": 60.00,
  "expires_at": "2026-11-24T14:35:00+05:30"
}
```

The values must be read from Parking's committed booking record. The frontend cannot choose the amount, owner, booking status, or hold expiry.

### Response

New payment: `201 Created`. Idempotent replay with identical immutable values: `200 OK`.

```json
{
  "payment_id": "<payment-uuid>",
  "booking_id": "<booking-uuid>",
  "amount": 60.00,
  "status": "PENDING",
  "expires_at": "2026-11-24T14:35:00+05:30"
}
```

### Idempotency

Payment Service enforces `UNIQUE(booking_id)`. A retry with the same booking ID and matching user, amount and expiry returns the existing payment. A retry with conflicting immutable values returns `409 PAYMENT_REQUEST_CONFLICT`.

The Parking-side booking-create request itself also needs an idempotency strategy; this is a separate open decision because Payment's uniqueness constraint alone does not prevent duplicate booking rows.

## 7. Payment-to-Parking callback contract

### Request

```http
POST /internal/v1/bookings/{booking_id}/payment-result
Content-Type: application/json
```

```json
{
  "payment_id": "<payment-uuid>",
  "status": "SUCCESS",
  "transaction_id": "TXN83921",
  "processed_at": "2026-11-24T14:33:00+05:30"
}
```

For a failed result, `status` is `FAILED` and `transaction_id` is null.

### Parking validation

Parking must authenticate Payment Service, lock the booking, verify the payment ID, verify that the booking is still pending, and evaluate hold expiry using Parking's own database/service time. It must not trust `processed_at` supplied by Payment as the authority for hold validity.

### Idempotency

- Repeated identical callback for an already-applied result: acknowledge without repeating the transition.
- Mismatched payment ID: reject and log.
- Conflicting result for an already-terminal booking: reject for investigation; never overwrite a confirmed booking with a different payment outcome.

## 8. User identity and access tokens

### Agreed token model

- Short-lived application access token in **RS256** JWT format.
- Refresh token/session stored and revocable by User/Auth Service, delivered to browser clients as a **Secure, HttpOnly cookie** with **refresh-token rotation**.
- `POST /api/v1/auth/refresh` is approved and included in the baseline.
- Services validate user identity locally from the signed RS256 access token rather than asking User/Auth on every request.

A candidate access-token claim set is:

```json
{
  "iss": "<configured-user-auth-issuer>",
  "aud": "corporate-parking",
  "sub": "<user-uuid>",
  "iat": 1795350000,
  "exp": 1795350900
}
```

`sub` is the canonical application user ID. Services derive `user_id` from `sub`; they must not trust a client-supplied user ID.

### Agreed signing model (RS256)

- User/Auth holds the private signing key.
- Gateway and downstream services validate signatures with the public key.
- Other services cannot mint application tokens.

Remaining open JWT/session details: exact issuer/audience claims, access/refresh token lifetimes, key storage/rotation, and reuse-detection semantics.

### Validation responsibilities

- Gateway validates access tokens as an early rejection layer.
- Each business service validates the token independently before applying user-scoped operations.
- Validate signature, issuer, audience, expiry and required subject claim.
- A valid token is not permission to access every record: each service still enforces ownership using its own data.

## 9. Internal service authentication

Internal endpoints must authenticate the calling service, not merely trust that the URL is difficult to guess.

### Agreed internal service authentication (Sprint Demo Baseline)

Use the standardized header `X-Internal-Service-Token` with per-direction environment secrets:

- `PARKING_TO_VEHICLE_TOKEN`
- `PARKING_TO_PAYMENT_TOKEN`
- `PAYMENT_TO_PARKING_TOKEN`
- `VEHICLE_TO_PARKING_TOKEN`

Do not use one global token shared by all services.

For `Parking → Vehicle` (`GET /api/v1/vehicles/{vehicle_id}`): Parking forwards the authenticated user's `Authorization: Bearer <user-jwt>` **plus** `X-Internal-Service-Token: <PARKING_TO_VEHICLE_TOKEN>`. Vehicle Service validates both the internal service token and the user JWT independently (never trusts an arbitrary `X-User-ID` header).

For `Parking → Payment`, `Payment → Parking`, and `Vehicle → Parking`, the receiver validates `X-Internal-Service-Token` against the expected caller token via a FastAPI dependency.

### Gateway protection

- The Gateway must strip any externally supplied internal-authentication headers before forwarding public traffic.
- The Gateway must never add internal service credentials to frontend-bound requests.
- Internal endpoints must not be present in the public route table.
- Internal secrets must never be committed to Git or written to logs.

### Future hardening

mTLS, a centralized workload identity platform, automated secret rotation and network policy are possible production improvements. They are not required to add more microservices to the current project.

## 10. Corporate email OTP verification security

- Normalize email consistently before domain checks and storage.
- Compare the domain to `COMPANY_EMAIL_DOMAIN`; do not hardcode a domain in application logic.
- Generate a cryptographically secure 6-digit random code.
- Store a keyed HMAC-SHA256 hash (`OTP_HMAC_SECRET`), never the plaintext code.
- Expire codes after the planned five-minute lifetime.
- Invalidate the previous active code when a new one is issued.
- Enforce attempt (max 5) and resend cooldown (60s) limits via PostgreSQL.
- Consume a code after successful use; do not allow replay.
- Never include the code in API responses or production logs.

Google OAuth is explicitly excluded from scope; authentication is purely corporate-email OTP based.

## 11. Authorization rules by resource

| Resource/action | Authorization rule |
|---|---|
| User profile | Authenticated user can retrieve only their own profile |
| Vehicle list/get/update/deactivate | Owner only |
| Availability | Authenticated user; referenced vehicle must belong to user |
| Booking list/get/cancel | Booking owner only |
| Payment get/process | Payment owner only, checked using Payment DB `user_id` |
| Internal payment creation | Parking service identity only |
| Payment result callback | Payment service identity only |
| Vehicle dependency lookup | Approved internal Vehicle-to-Parking call (Vehicle service identity only) |

For non-owned resources, return a consistent non-disclosing response, normally `404`.

## 12. Other Gateway responsibilities

The Gateway may handle:
- public route matching;
- CORS policy for the known frontend origin(s);
- maximum request size and basic request parsing controls;
- correlation/request ID forwarding or generation;
- early token validation;
- safe propagation of service errors.

It must not:
- calculate booking prices;
- check booking overlap;
- select/lock parking slots;
- change booking or payment state;
- query service databases.

## 13. Data protection and logging

- Use HTTPS in deployed environments.
- Do not log access tokens, refresh tokens, OTPs, service credentials, UPI PINs, card data or other secrets.
- Do not collect real card/UPI credentials in the simulated payment flow.
- Log service name, request/correlation ID, route, outcome, duration and sanitized error context.
- Avoid logging unnecessary personal data such as full email addresses or vehicle numbers; mask where practical.
- Keep secrets and service URLs outside source code, using environment configuration for local development and a suitable secret store for deployment.

## 14. Security/integration status (m0 finalized)

Core security and integration decisions are finalized for the sprint demo baseline (`decisions-and-open-questions.md`):
- RS256 access JWT (15-min lifetime, claims `iss`/`aud`/`sub`/`iat`/`exp`), 7-day opaque refresh token in Secure HttpOnly cookie with rotation, dev RSA keypair loaded from env.
- Internal service auth via `X-Internal-Service-Token` with per-direction env tokens; Gateway strips `X-Internal-Service-Token` and blocks `/internal/v1/*`.
- `Parking → Vehicle` forwards `Authorization: Bearer <jwt>` + `X-Internal-Service-Token`.
- Only deployment-environment items (production CORS origins, HTTPS/network boundaries, secret rotation) remain for later phases.
