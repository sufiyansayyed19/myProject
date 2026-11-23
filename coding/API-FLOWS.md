# Corporate Parking Reservation System — API Flow Diagrams

Visual guide to all **22 APIs** across the **API Gateway** (`8000`) and **4 Business Microservices** (`8001`–`8004`), reflecting the implemented codebase.

---

## 1. System Overview & API Gateway Routing (`gateway/` — Port `8000`)

The Gateway is infrastructure-only (no database, no business logic). It enforces early RS256 JWT validation on protected routes, blocks `/internal/v1/*` with `404`, strips any externally supplied `X-Internal-Service-Token`, and forwards `X-Request-ID`. Internal service-to-service calls bypass the Gateway.

```mermaid
flowchart LR
    Client["Frontend / Swagger / Client"] -->|"Public HTTPS/HTTP + X-Request-ID"| GW["API Gateway (:8000)"]

    GW -->|"/internal/* -> 404 BLOCKED"| Blocked["404 NOT_FOUND"]
    GW -->|"/api/v1/auth/* (Public)"| Auth["User/Auth Service (:8001)"]
    GW -->|"/api/v1/users/* (RS256 JWT)"| Auth
    GW -->|"/api/v1/vehicles/* (RS256 JWT)"| Veh["Vehicle Service (:8002)"]
    GW -->|"/api/v1/parking/* (RS256 JWT)"| Park["Parking Service (:8003)"]
    GW -->|"/api/v1/payments/* (RS256 JWT)"| Pay["Payment Service (:8004)"]

    Auth --- UDB[("user_db")]
    Veh --- VDB[("vehicle_db")]
    Park --- PDB[("parking_db")]
    Pay --- PAYDB[("payment_db")]

    Park -.->|"GET /api/v1/vehicles/{id}\n(User JWT + PARKING_TO_VEHICLE_TOKEN)"| Veh
    Veh -.->|"GET /internal/v1/vehicles/{id}/booking-dependency\n(VEHICLE_TO_PARKING_TOKEN)"| Park
    Park -.->|"POST /internal/v1/payments\n(PARKING_TO_PAYMENT_TOKEN)"| Pay
    Pay -.->|"POST /internal/v1/bookings/{id}/payment-result\n(PAYMENT_TO_PARKING_TOKEN)"| Park
```

---

## 2. User/Auth Service (`services/user-auth-service` — Port `8001`, 7 APIs)

### 2.1 Company Email OTP, Profile, Token Refresh & Logout

```mermaid
sequenceDiagram
    participant C as Client
    participant GW as API Gateway (:8000)
    participant A as User/Auth (:8001)
    participant DB as user_db
    participant Mail as EmailSender (Console/SMTP)

    Note over C,Mail: 1. Send Corporate Email OTP
    C->>GW: POST /api/v1/auth/company/send-code {email}
    GW->>A: Forward request
    A->>A: Normalize email & check COMPANY_EMAIL_DOMAIN (403 if invalid)
    A->>DB: Check 60s resend cooldown (429 if too soon)
    A->>DB: Invalidate old active codes & insert HMAC-SHA256 OTP (5m TTL)
    A->>Mail: send_otp(email, 6-digit code)
    A-->>C: 200 {"message": "Verification code sent successfully"}

    Note over C,Mail: 2. Verify OTP & Issue Tokens
    C->>GW: POST /api/v1/auth/company/verify {email, code}
    GW->>A: Forward request
    A->>DB: Load latest active VerificationCode
    alt Wrong code
        A->>DB: Increment attempt_count (invalidate & 429 at max 5)
        A-->>C: 401 INVALID_OR_EXPIRED_CODE
    else Valid code
        A->>DB: Mark consumed_at; find/create User & COMPANY_EMAIL AuthIdentity
        A->>DB: Insert SHA-256 RefreshSession (7d TTL)
        A-->>C: 200 {access_token (RS256 15m), user} + Set-Cookie: refresh_token (HttpOnly)
    end

    Note over C,Mail: 3. Fetch Current Profile
    C->>GW: GET /api/v1/users/me (Authorization: Bearer JWT)
    GW->>GW: Early RS256 JWT validation
    GW->>A: Forward request
    A->>DB: Lookup User by JWT sub
    A-->>C: 200 {id, email, name}

    Note over C,Mail: 4. Refresh Token Rotation & Logout
    C->>GW: POST /api/v1/auth/refresh (Cookie: refresh_token)
    GW->>A: Forward with cookie
    A->>DB: Validate unrevoked/unexpired session -> revoke old -> insert new session
    A-->>C: 200 {new access_token} + Set-Cookie: rotated refresh_token

    C->>GW: POST /api/v1/auth/logout (Cookie: refresh_token)
    GW->>A: Forward with cookie
    A->>DB: Set revoked_at on session (idempotent)
    A-->>C: 200 {"message": "Logged out successfully"} + Clear cookie
```

### 2.2 Google OAuth 2.0 & Verified Account Linking

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as User/Auth (:8001)
    participant G as Google OAuth
    participant DB as user_db

    B->>A: GET /api/v1/auth/google
    A-->>B: 302 Redirect to accounts.google.com + Set-Cookie: oauth_state (HttpOnly)
    B->>G: User signs in & consents
    G-->>B: 302 Redirect to /api/v1/auth/google/callback?code=...&state=...
    B->>A: GET /api/v1/auth/google/callback (Cookie: oauth_state)
    A->>A: Constant-time check state == oauth_state (400 if mismatch)
    A->>G: POST /token (exchange code) + GET /userinfo
    G-->>A: {sub, email, email_verified, name}
    A->>A: Require email_verified=true & corporate domain (403 otherwise)
    A->>DB: Lookup GOOGLE identity -> else match verified User.email (auto-link!) -> else create User
    A->>DB: Create RefreshSession
    A-->>B: 302 Redirect to FRONTEND_AUTH_SUCCESS_URL + Set-Cookie: refresh_token
```

---

## 3. Vehicle Service (`services/vehicle-service` — Port `8002`, 5 APIs)

```mermaid
sequenceDiagram
    participant C as Client
    participant GW as API Gateway (:8000)
    participant V as Vehicle (:8002)
    participant VDB as vehicle_db
    participant P as Parking (:8003)

    Note over C,VDB: 1. Register & Read Vehicles (Owner-Scoped)
    C->>GW: POST /api/v1/vehicles {vehicle_number, vehicle_type, is_ev}
    GW->>GW: Validate RS256 JWT & strip X-Internal-Service-Token
    GW->>V: Forward request
    V->>V: Validate JWT + normalize plate (uppercase, strip spaces/hyphens)
    V->>VDB: Insert active vehicle (partial unique index WHERE is_active = true)
    V-->>C: 201 {id, vehicle_number, vehicle_type, is_ev, is_active: true}

    C->>GW: GET /api/v1/vehicles  |  GET /api/v1/vehicles/{id}
    GW->>V: Forward request
    V->>VDB: Query WHERE user_id = sub AND is_active = true (404 if non-owned/inactive)
    V-->>C: 200 Vehicle list or single vehicle

    Note over C,P: 2. Update (PUT) or Soft-Deactivate (DELETE) with Dependency Check
    C->>GW: PUT or DELETE /api/v1/vehicles/{id}
    GW->>V: Forward request
    V->>VDB: Verify owner & active status (404 if not found)
    V->>P: GET /internal/v1/vehicles/{id}/booking-dependency (X-Internal-Service-Token)
    alt Parking unreachable
        P--xV: Timeout / Error
        V-->>C: 503 PARKING_SERVICE_UNAVAILABLE (fail closed)
    else has_blocking_booking == true
        P-->>V: 200 {has_blocking_booking: true}
        V-->>C: 409 VEHICLE_HAS_BLOCKING_BOOKING
    else has_blocking_booking == false
        P-->>V: 200 {has_blocking_booking: false}
        V->>VDB: Apply PUT update OR set is_active = false (soft delete)
        V-->>C: 200 Updated vehicle / {"is_active": false, "message": "Vehicle removed successfully"}
    end
```

---

## 4. Parking Service (`services/parking-service` — Port `8003`, 5 Public + 2 Internal APIs)

### 4.1 Availability & Atomic Booking Creation (Locking + Idempotency + Hold)

```mermaid
sequenceDiagram
    participant C as Client
    participant GW as API Gateway (:8000)
    participant P as Parking (:8003)
    participant V as Vehicle (:8002)
    participant PDB as parking_db
    participant PAY as Payment (:8004)

    Note over C,PDB: 1. Informational Availability Check
    C->>GW: GET /api/v1/parking/availability?date&start_time&end_time&vehicle_id&requires_charging
    GW->>P: Forward (RS256 JWT validated)
    P->>P: Validate calendar/hours/15m-advance/same-hour rules (Asia/Kolkata)
    P->>V: GET /api/v1/vehicles/{id} (User JWT + PARKING_TO_VEHICLE_TOKEN)
    V-->>P: {vehicle_type, is_ev, is_active}
    P->>P: Reject non-EV requesting charging (422 CHARGING_NOT_SUPPORTED)
    P->>PDB: Count compatible slots not overlapping CONFIRMED or unexpired PAYMENT_PENDING
    P-->>C: 200 {available, available_slots, rate_per_hour (10 or 20)}

    Note over C,PAY: 2. Create Booking (Atomic Allocation + 5-Min Hold)
    C->>GW: POST /api/v1/parking/bookings (Header: Idempotency-Key UUID)
    GW->>P: Forward request
    P->>PDB: Check (user_id, Idempotency-Key)
    alt Key exists with same payload
        P-->>C: 200 Replay original booking
    else Key exists with different payload
        P-->>C: 409 IDEMPOTENCY_CONFLICT
    else New request
        P->>P: Validate time rules + call Vehicle Service + calculate amount (₹10/₹20 per hr)
        rect rgb(235, 245, 255)
            Note over P,PDB: Single PostgreSQL Transaction
            P->>PDB: pg_advisory_xact_lock(user_id)
            P->>PDB: Check same-user overlap (409 USER_BOOKING_OVERLAP)
            P->>PDB: SELECT compatible parking_slots ORDER BY slot_number ASC FOR UPDATE
            P->>PDB: Pick first non-overlapping slot (409 NO_PARKING_CAPACITY if none)
            P->>PDB: INSERT Booking (PAYMENT_PENDING, 5m hold, vehicle snapshots) + IdempotencyKey
            P->>PDB: COMMIT (before calling Payment Service!)
        end
        P->>PAY: POST /internal/v1/payments (up to 2 inline retries, PARKING_TO_PAYMENT_TOKEN)
        PAY-->>P: 201 {payment_id, status: PENDING}
        P->>PDB: UPDATE bookings SET payment_id = ... & COMMIT
        P-->>C: 201 {booking_id, slot_number, snapshots, amount, status: PAYMENT_PENDING, payment_id, hold_expires_at}
    end
```

### 4.2 Booking History, Lazy Hold Expiry & Cancellation

```mermaid
sequenceDiagram
    participant C as Client
    participant GW as API Gateway (:8000)
    participant P as Parking (:8003)
    participant PDB as parking_db

    Note over C,PDB: 1. List / Detail (with Lazy Hold Expiry)
    C->>GW: GET /api/v1/parking/bookings?page=1&page_size=20  |  GET /api/v1/parking/bookings/{id}
    GW->>P: Forward request
    P->>PDB: Query owner's bookings
    P->>PDB: If any PAYMENT_PENDING has hold_expires_at <= now -> flip to EXPIRED
    P-->>C: 200 Paginated items or single booking

    Note over C,PDB: 2. Cancel Confirmed Booking
    C->>GW: POST /api/v1/parking/bookings/{id}/cancel
    GW->>P: Forward request
    P->>PDB: SELECT booking FOR UPDATE (owner-scoped, 404 if missing)
    P->>P: Require status == CONFIRMED AND (start_time - now) > 5 minutes
    alt Not confirmed or <= 5 min before start
        P-->>C: 409 BOOKING_NOT_CANCELLABLE
    else Eligible
        P->>PDB: UPDATE status = CANCELLED, cancelled_at = now
        P-->>C: 200 {booking_id, status: CANCELLED, cancelled_at}
    end
```

### 4.3 Booking State Machine

```mermaid
stateDiagram-v2
    [*] --> PAYMENT_PENDING: POST /bookings (5-min hold)
    PAYMENT_PENDING --> CONFIRMED: Payment callback SUCCESS (while hold valid)
    PAYMENT_PENDING --> EXPIRED: Payment callback FAILED
    PAYMENT_PENDING --> EXPIRED: Hold expires (lazy expiry or late callback)
    CONFIRMED --> CANCELLED: POST /cancel (> 5 min before start)
    EXPIRED --> [*]
    CANCELLED --> [*]
```

---

## 5. Payment Service (`services/payment-service` — Port `8004`, 1 Internal + 2 Public APIs)

```mermaid
sequenceDiagram
    participant C as Client
    participant GW as API Gateway (:8000)
    participant PAY as Payment (:8004)
    participant PAYDB as payment_db
    participant P as Parking (:8003)
    participant PDB as parking_db

    Note over P,PAYDB: 1. Internal Payment Creation (Called by Parking Service)
    P->>PAY: POST /internal/v1/payments {booking_id, user_id, amount, expires_at}
    PAY->>PAY: Validate PARKING_TO_PAYMENT_TOKEN (401 if invalid)
    PAY->>PAYDB: Check UNIQUE(booking_id) (200 replay if identical, 409 if conflicting)
    PAY->>PAYDB: INSERT Payment (status = PENDING)
    PAY-->>P: 201 {payment_id, booking_id, amount, status: PENDING, expires_at}

    Note over C,PDB: 2. Process Simulated Payment & Deliver Callback
    C->>GW: POST /api/v1/payments/{id}/process {payment_method: UPI|CARD|WALLET}
    GW->>PAY: Forward (RS256 JWT validated)
    PAY->>PAYDB: SELECT payment FOR UPDATE (owner-scoped, 404 if non-owned)
    PAY->>PAY: Reject if status != PENDING (409) or now >= expires_at (409)
    PAY->>PAY: Resolve deterministic outcome (env default or non-prod X-Test-Payment-Outcome)
    PAY->>PAYDB: COMMIT final status (SUCCESS + TXN... or FAILED) BEFORE callback!
    PAY->>P: POST /internal/v1/bookings/{booking_id}/payment-result (up to 2 inline retries)
    P->>P: Validate PAYMENT_TO_PARKING_TOKEN
    P->>PDB: Lock booking, verify payment_id, check Parking clock (never resurrect EXPIRED!)
    P->>PDB: Transition PAYMENT_PENDING -> CONFIRMED or EXPIRED (idempotent on duplicates)
    P-->>PAY: 200 {booking_id, status, result: APPLIED | ALREADY_APPLIED}
    PAY->>PAYDB: Save callback_attempts, callback_delivered_at, callback_last_error
    PAY-->>C: 200 {payment_id, booking_id, amount, status, transaction_id}

    Note over C,PAYDB: 3. Retrieve Payment Details
    C->>GW: GET /api/v1/payments/{id}
    GW->>PAY: Forward request
    PAY->>PAYDB: SELECT WHERE id = payment_id AND user_id = sub (404 if non-owned)
    PAY-->>C: 200 Payment details
```

---

## 6. Complete End-to-End User Journey (All 5 Apps)

```mermaid
sequenceDiagram
    participant U as Employee
    participant GW as API Gateway (:8000)
    participant A as User/Auth (:8001)
    participant V as Vehicle (:8002)
    participant P as Parking (:8003)
    participant PAY as Payment (:8004)

    U->>GW: 1. Login (Email OTP or Google OAuth)
    GW->>A: Authenticate
    A-->>U: RS256 access_token + HttpOnly refresh_token

    U->>GW: 2. POST /api/v1/vehicles (Register EV Car)
    GW->>V: Save vehicle
    V-->>U: 201 {vehicle_id}

    U->>GW: 3. GET /api/v1/parking/availability
    GW->>P: Check availability
    P->>V: Validate vehicle ownership & EV flag
    V-->>P: Vehicle OK
    P-->>U: 200 {available: true, rate_per_hour: 20}

    U->>GW: 4. POST /api/v1/parking/bookings (Idempotency-Key)
    GW->>P: Create 5-min hold
    P->>V: Re-validate vehicle
    P->>PAY: POST /internal/v1/payments
    PAY-->>P: 201 {payment_id}
    P-->>U: 201 {booking_id, slot_number, status: PAYMENT_PENDING, payment_id}

    U->>GW: 5. POST /api/v1/payments/{payment_id}/process {UPI}
    GW->>PAY: Simulate payment
    PAY->>P: POST /internal/v1/bookings/{booking_id}/payment-result (SUCCESS)
    P-->>PAY: 200 {status: CONFIRMED}
    PAY-->>U: 200 {status: SUCCESS, transaction_id}

    U->>GW: 6. GET /api/v1/parking/bookings/{booking_id}
    GW->>P: Fetch booking
    P-->>U: 200 {status: CONFIRMED}

    U->>GW: 7. POST /api/v1/parking/bookings/{booking_id}/cancel (> 5 min before start)
    GW->>P: Cancel booking
    P-->>U: 200 {status: CANCELLED}
```
