# User/Auth Service API Contract

**Document status:** Finalized baseline. Authentication is purely based on **corporate email OTP verification** (`COMPANY_EMAIL_DOMAIN`). Google OAuth was explicitly dropped from scope because the system serves company employees exclusively.

## 1. Responsibilities and boundaries

User/Auth Service owns user identity, corporate-email verification records, authentication identities, and refresh sessions. It does not own vehicles, bookings, slots, or payments.

Successful corporate-email OTP verification resolves to one application user identity. A separate registration endpoint is not required: the first successful verification creates the user and `COMPANY_EMAIL` authentication identity.

## 2. Endpoint inventory (5 endpoints)

| Method | Endpoint | Caller | Purpose | Status |
|---|---|---|---|---|
| POST | `/api/v1/auth/company/send-code` | Frontend | Start corporate-email OTP verification | Agreed (in baseline) |
| POST | `/api/v1/auth/company/verify` | Frontend | Verify OTP code and authenticate | Agreed (in baseline) |
| GET | `/api/v1/users/me` | Frontend | Retrieve current user profile | Agreed (in baseline) |
| POST | `/api/v1/auth/refresh` | Frontend | Rotate refresh session and issue new RS256 access token | Agreed (in baseline) |
| POST | `/api/v1/auth/logout` | Frontend | Revoke refresh session | Agreed (in baseline) |

## 3. Shared conventions

- All public endpoints are under `/api/v1` and are routed through the API Gateway.
- Authenticated endpoints require the application's RS256 Bearer access token.
- User identity is taken from the validated token subject (`sub`), never from a client-supplied `user_id`.
- Email addresses are normalized consistently (trimmed and lowercased).
- Standard error envelope: `{ "error": { "code", "message", "request_id" } }`.

## 4. `POST /api/v1/auth/company/send-code`

### Request

```json
{
  "email": "employee@company.com"
}
```

### Processing and validation

1. Validate email syntax and normalize the address.
2. Check that its domain matches the configured corporate domain (`COMPANY_EMAIL_DOMAIN`). Reject non-corporate domains with `403 CORPORATE_EMAIL_REQUIRED`.
3. Enforce DB-based resend cooldown (`OTP_RESEND_COOLDOWN_SECONDS`, default 60s) -> `429 OTP_RATE_LIMITED`.
4. Invalidate any previous active code for the same email in the same transaction.
5. Generate a cryptographically random 6-digit OTP, store its keyed HMAC-SHA256 hash (`OTP_HMAC_SECRET`), and set a 5-minute expiry (`OTP_EXPIRE_MINUTES`).
6. Send the code through the **pluggable `EmailSender` interface** (`ConsoleEmailSender` in local dev; never expose OTPs in API responses; never log OTPs in production; ready for SMTP/provider later).

### Response (`200 OK`)

```json
{
  "message": "Verification code sent successfully"
}
```

### Errors
- `403 CORPORATE_EMAIL_REQUIRED` — Domain does not match `COMPANY_EMAIL_DOMAIN`.
- `422 INVALID_REQUEST` — Invalid email syntax.
- `429 OTP_RATE_LIMITED` — Resend cooldown not yet elapsed.
- `502 EMAIL_DELIVERY_FAILED` — External email sender failed.

## 5. `POST /api/v1/auth/company/verify`

### Request

```json
{
  "email": "employee@company.com",
  "code": "482731"
}
```

### Processing

1. Normalize email and locate the latest active, unexpired verification record.
2. Reject missing, expired, consumed, or invalidated codes with `401 INVALID_OR_EXPIRED_CODE`.
3. Verify submitted code against stored HMAC hash in constant time.
4. On mismatch, increment `attempt_count`; invalidate and return `429 OTP_ATTEMPTS_EXCEEDED` at `OTP_MAX_ATTEMPTS` (default 5).
5. On match, mark `consumed_at`, find or create `User` and `COMPANY_EMAIL` `AuthIdentity`.
6. Issue a short-lived **RS256** access JWT (15-min expiry) and create a 7-day `RefreshSession` set as a `Secure, HttpOnly` cookie (`refresh_token`).

### Response (`200 OK`)

```json
{
  "access_token": "<rs256-access-token>",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "<user-uuid>",
    "email": "employee@company.com",
    "name": null
  }
}
```

## 6. `GET /api/v1/users/me`

Requires `Authorization: Bearer <rs256-access-token>`. Returns `{ "id", "email", "name" }` (`200 OK`) or `401 UNAUTHENTICATED`.

## 7. `POST /api/v1/auth/refresh`

Reads the `refresh_token` HttpOnly cookie, validates that the hashed session exists, is unrevoked, and is unexpired, **rotates** the refresh session (revokes old, inserts new, sets rotated cookie), and returns a fresh RS256 access token (`200 OK`). Reusing a revoked refresh token returns `401 UNAUTHENTICATED`.

## 8. `POST /api/v1/auth/logout`

Reads the `refresh_token` cookie, idempotently sets `revoked_at` on the session, clears the cookie, and returns `200 OK` (`{"message": "Logged out successfully"}`).

## 9. Excluded endpoints

Google OAuth (`/api/v1/auth/google`, `/api/v1/auth/google/callback`), password login, password reset, registration, profile update, and account deletion are excluded from scope.
