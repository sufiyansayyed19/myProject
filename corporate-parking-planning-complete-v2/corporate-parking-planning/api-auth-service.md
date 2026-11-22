# User/Auth Service API Contract

**Document status:** Technical design baseline. Endpoint inventory is inherited from the planning discussion; details marked **Proposed** or **Open** require confirmation before implementation.

## 1. Responsibilities and boundaries

User/Auth Service owns user identity, corporate-email verification records, authentication identities, and refresh sessions. It does not own vehicles, bookings, slots, or payments.

Authentication options in the current scope:

1. Corporate email verification code.
2. Google OAuth, subject to the same configured corporate-domain eligibility rule.

Successful authentication resolves to one application user identity. A separate registration endpoint is not required: the first successful verification can create the user and authentication identity.

## 2. Endpoint inventory

| Method | Endpoint | Caller | Purpose | Status |
|---|---|---|---|---|
| POST | `/api/v1/auth/company/send-code` | Frontend | Start corporate-email verification | Agreed (in baseline) |
| POST | `/api/v1/auth/company/verify` | Frontend | Verify code and authenticate | Agreed (in baseline) |
| GET | `/api/v1/auth/google` | Browser/frontend | Start Google OAuth | Agreed (in baseline) |
| GET | `/api/v1/auth/google/callback` | Google redirect | Complete OAuth and authenticate | Agreed (in baseline) |
| GET | `/api/v1/users/me` | Frontend | Retrieve current user profile | Agreed (in baseline) |
| POST | `/api/v1/auth/logout` | Frontend | Revoke refresh session | Agreed (in baseline) |
| POST | `/api/v1/auth/refresh` | Frontend | Exchange valid refresh session for a new access token | Agreed (approved and added to baseline) |

The User/Auth Service baseline contains **7 endpoints**, including `POST /api/v1/auth/refresh` to support the approved short-lived RS256 access JWT + revocable refresh-session model.

## 3. Shared conventions

- All public endpoints are under `/api/v1` and are routed through the API Gateway.
- Authenticated endpoints require the application's access token.
- User identity is taken from the validated token subject (`sub`), never from a client-supplied `user_id`.
- Email addresses should be normalized consistently (at minimum trim whitespace and lowercase the domain; a consistent full-address lowercase policy is recommended).
- Business timezone is `Asia/Kolkata`; token/session timestamps are stored as timezone-aware timestamps.
- A consistent error envelope is planned for all services, but the exact common format is finalized in `quality-and-testing-plan.md` / the decision register.

## 4. `POST /api/v1/auth/company/send-code`

### Purpose

Start authentication by sending a one-time verification code to an eligible corporate email address.

### Request

```json
{
  "email": "employee@company.com"
}
```

### Processing and validation

1. Validate the email syntax and normalize the address.
2. Check that its domain matches the configured allow-list/domain, for example `COMPANY_EMAIL_DOMAIN=company.com`. The value must be configuration, not hardcoded.
3. Apply rate limits for the email and, where appropriate, the requester/IP.
4. Generate a cryptographically random numeric code. A six-digit code is the current **proposal** based on examples in the design discussion.
5. Store a protected representation of the code, not plaintext. Because a short numeric code has low entropy, a keyed HMAC or similarly protected verification value is preferable to an unkeyed fast hash alone.
6. Invalidate any previous active code for the same email in the same transaction that creates the new code.
7. Set a short expiry. Five minutes is the current **proposed** lifetime.
8. Send the code through a **pluggable email sender interface** so the delivery implementation can change without changing authentication business logic:
   - Local development: use a console/log-based mock sender; never expose OTPs in API responses; never log OTPs in production.
   - Production-ready path: configurable SMTP or external corporate email provider later.

The email provider is external; email delivery logic does not become a separate microservice.

### Response

The earlier contract used `200 OK`; retain that response if code delivery completes synchronously.

```json
{
  "message": "Verification code sent successfully"
}
```

Do not return the code in the response, logs, or API documentation examples.

### Errors

| HTTP | Example error code | Meaning |
|---:|---|---|
| 400 | `INVALID_EMAIL` | Email syntax is invalid |
| 403 | `CORPORATE_EMAIL_REQUIRED` | Domain is not permitted |
| 429 | `OTP_RATE_LIMITED` | Request limit reached |
| 502 | `EMAIL_DELIVERY_FAILED` | External email provider failed |
| 500 | `INTERNAL_ERROR` | Unexpected internal failure |

### Proposed abuse controls

- Code lifetime: five minutes.
- Maximum verification attempts per code: five.
- Resending creates a new code and invalidates the previous active code.
- Rate-limit code sending and verification attempts.

These numeric limits were recommended in the discussion but should remain configurable and be confirmed before implementation.

## 5. `POST /api/v1/auth/company/verify`

### Purpose

Verify a previously issued code and establish an application-authenticated identity.

### Request

```json
{
  "email": "employee@company.com",
  "code": "482731"
}
```

### Processing

1. Normalize email and locate the latest active, unexpired verification record.
2. Reject a missing, expired, consumed, invalidated, or exhausted code.
3. Verify the submitted code against the stored protected representation.
4. Increment failed-attempt count on mismatch; invalidate the code when the configured attempt limit is reached.
5. On success, mark the code consumed.
6. Find or create the application user for the normalized corporate email.
7. Associate the company-email authentication identity with the user.
8. Issue the application's access token and create a refresh session if that model is adopted.

### Response — proposed token shape

```json
{
  "access_token": "<application-access-token>",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "<user-uuid>",
    "email": "employee@company.com",
    "name": null
  }
}
```

`name` may be null for email-only authentication because code verification does not itself establish the person's name. Google may provide a verified profile name, subject to the identity-matching policy. The `expires_in: 900` value in this example is illustrative only; exact token lifetime remains open.

**Agreed token & refresh transport:** issue a short-lived **RS256** access JWT in the response body and store the refresh token in a **Secure, HttpOnly cookie** for browser clients, with refresh-token rotation and refresh-session validation/revocation in User/Auth Service. Do not place refresh tokens in JSON responses or browser local storage.

### Errors

| HTTP | Example error code | Meaning |
|---:|---|---|
| 400 | `INVALID_REQUEST` | Missing or malformed fields |
| 401 | `INVALID_OR_EXPIRED_CODE` | Code is wrong, expired, consumed, or invalidated |
| 429 | `OTP_ATTEMPTS_EXCEEDED` | Attempt/rate limit reached |
| 500 | `INTERNAL_ERROR` | Unexpected failure |

Do not reveal whether a user record already existed. A successful first verification may create the user.

## 6. `GET /api/v1/auth/google`

### Purpose

Start the Google OAuth authorization flow.

### Request

No request body. Browser navigates to this endpoint.

### Processing

- Generate a cryptographically random OAuth `state` value and validate it on callback.
- Use environment variables for Google client ID, Google client secret, redirect URI, and allowed corporate email domain. Do not hardcode credentials or commit secrets.
- Use an approved redirect destination; do not accept arbitrary user-supplied redirect URLs.
- Request only the identity/profile scopes needed by the application.
- Use PKCE where supported by the selected OAuth client flow.

### Response

`302 Found` redirect to Google's authorization endpoint.

No application JWT is issued at this stage.

## 7. `GET /api/v1/auth/google/callback`

### Purpose

Receive Google's redirect and complete OAuth authentication.

### Query parameters

Google supplies the authorization `code` and the previously generated `state` (or an OAuth error). They are callback parameters, not user profile data to trust without verification.

### Processing

1. Validate `state` and the OAuth flow/session correlation.
2. Exchange the authorization code with Google server-to-server.
3. Validate the identity information returned by Google, including verified email and provider subject.
4. Enforce the corporate-domain eligibility policy.
5. Resolve or create the application user and Google authentication identity.
6. Issue application access/refresh credentials using the same policy as company-email authentication.
7. Redirect the browser to a fixed, allow-listed frontend destination.

The frontend must use the application's token/session, not treat a Google access token as the application's access token.

### Response

Successful callback: redirect to an allow-listed frontend route, with authentication established using the agreed secure cookie/token handoff.

Failure: redirect to a safe frontend error route or return an appropriate error response; do not put provider access tokens or sensitive error details into redirect query strings.

### Errors

| HTTP / behavior | Example | Meaning |
|---|---|---|
| 400 | `INVALID_OAUTH_STATE` | State mismatch or invalid callback |
| 401 | `GOOGLE_AUTHENTICATION_FAILED` | Provider authentication failed |
| 403 | `CORPORATE_GOOGLE_ACCOUNT_REQUIRED` | Google identity fails eligibility policy |
| 502 | `GOOGLE_PROVIDER_UNAVAILABLE` | Provider/token exchange unavailable |

## 8. `GET /api/v1/users/me`

### Purpose

Return the user identity associated with the current access token.

### Authentication

Required:

```http
Authorization: Bearer <application-access-token>
```

### Response

```json
{
  "id": "<user-uuid>",
  "email": "employee@company.com",
  "name": null
}
```

Only public profile fields should be returned. Do not expose verification hashes, refresh-token hashes, or internal authentication metadata.

### Errors

- `401 UNAUTHENTICATED`: missing, invalid, or expired access token.

## 9. `POST /api/v1/auth/logout`

### Purpose

Revoke the current refresh session so it cannot be used to obtain future access tokens.

### Authentication

Requires a valid authenticated context and the refresh-session identifier/credential using the transport selected for the refresh token.

### Processing

- Identify the current refresh session.
- Set `revoked_at` if it has not already been revoked.
- Clear the browser refresh cookie if cookie-based transport is selected.
- Repeated logout should be safe; already-revoked sessions can still receive a successful response.

### Response

```json
{
  "message": "Logged out successfully"
}
```

### Important limitation

Revoking a refresh session does not invalidate an already-issued stateless access JWT immediately. That token remains usable until its short expiry unless a separate access-token revocation mechanism is introduced. The current design does not require a permanent JWT blacklist.

## 10. `POST /api/v1/auth/refresh`

**Status: Agreed** (approved and included in the 7-endpoint User/Auth Service baseline).

### Request

Browser clients send the Secure, HttpOnly refresh cookie automatically; no refresh token in JSON body.

### Processing

- Validate the refresh-session token, expiry, and revocation state in User/Auth Service.
- Perform **refresh-token rotation**: revoke/replace the used refresh session on successful refresh.
- Issue a new short-lived RS256 access JWT and set the rotated Secure, HttpOnly refresh cookie.

### Response

```json
{
  "access_token": "<new-application-access-token>",
  "token_type": "bearer",
  "expires_in": 900
}
```

## 11. Identity-linking policy — Agreed

**Agreed:** automatic account linking with verified identity:

1. Normalize both email addresses consistently.
2. Verify the company-email OTP identity.
3. For Google OAuth, require Google's `email_verified = true` and the configured corporate domain.
4. If the verified corporate emails match exactly, associate both provider identities with the same `users` record.
5. Never link identities based solely on an unverified email address.
6. Maintain separate provider identities in `auth_identities`, with unique `(provider, provider_subject)` combinations.

Remaining minor open items: how changes in a Google account's email are handled and whether `users.name` remains optional or a profile completion step is later introduced. No profile-update endpoint is currently in scope.

## 12. Excluded endpoints

No separate endpoints are planned for registration, password login, password reset, resend-code, change-password, profile update, or account deletion. Resending uses `send-code` again; first successful verification creates the user.
