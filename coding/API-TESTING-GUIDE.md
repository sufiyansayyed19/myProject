# API Manual Testing Guide (All 22 APIs)

Step-by-step handbook to manually test every endpoint using **Swagger UI** or **PowerShell (`curl.exe`)**, showing exact request bodies, headers, **where each value comes from**, and what response to expect.

---

## 0. Before You Start

1. **Migrate all 4 databases** (only needed once):
   ```powershell
   .\scripts\migrate_all.ps1
   ```
2. **Start all 5 apps** (Gateway `:8000` + 4 services `:8001`–`:8004`):
   ```powershell
   .\scripts\start_all.ps1
   ```
3. **Quick URLs:**
   - **API Gateway (use this for all public client/curl tests):** `http://127.0.0.1:8000`
   - **Swagger UIs (great for clicking through each service):**
     - User/Auth: `http://127.0.0.1:8001/docs`
     - Vehicle: `http://127.0.0.1:8002/docs`
     - Parking: `http://127.0.0.1:8003/docs`
     - Payment: `http://127.0.0.1:8004/docs`

### Cheat Sheet: Where Every Value Comes From

| Placeholder | Where You Get It |
|---|---|
| `<OTP_CODE>` | Printed in the **User/Auth Service (`8001`) terminal** as `[DEV EMAIL OTP] To: ... \| Code: 123456` |
| `<ACCESS_TOKEN>` | Returned in `access_token` from `POST /api/v1/auth/company/verify` or `POST /api/v1/auth/refresh` (valid 15 min) |
| `refresh_token` cookie | Set automatically by the browser on `/verify`, `/google/callback`, and `/refresh` (HttpOnly cookie) |
| `<VEHICLE_ID>` | Returned as `id` from `POST /api/v1/vehicles` or `GET /api/v1/vehicles` |
| `<IDEMPOTENCY_KEY>` | Any fresh UUID you generate per booking attempt — in PowerShell: `[guid]::NewGuid().ToString()` |
| `<BOOKING_ID>` | Returned as `booking_id` from `POST /api/v1/parking/bookings` |
| `<PAYMENT_ID>` | Returned as `payment_id` from `POST /api/v1/parking/bookings` |
| `<DATE>` | Today or tomorrow in `YYYY-MM-DD` (not Sunday! e.g. `2026-11-24`) |
| Internal tokens | Default dev values in each service's `app/core/config.py` (listed in Section 5 below) |

> **Tip for Swagger UI:** Click the green **Authorize 🔒** button at the top-right of Swagger (`8001`, `8002`, `8003`, `8004`) and paste **only** `<ACCESS_TOKEN>` (no `Bearer `, no quotes).

---

## 1. User/Auth Service (7 APIs — Port `8001`, via Gateway `8000`)

> **Check your domain:** Look at `COMPANY_EMAIL_DOMAIN` in `services/user-auth-service/.env` (default is `company.com`; if you set `gmail.com` for Google testing, use `@gmail.com` below).

### 1.1 `POST /api/v1/auth/company/send-code`
- **Auth:** None (public)
- **Body:**
  ```json
  {
    "email": "employee@company.com"
  }
  ```
- **Where values come from:** Any email matching `COMPANY_EMAIL_DOMAIN`.
- **Expected (`200 OK`):** `{"message": "Verification code sent successfully"}`
- **Next:** Look at the **User/Auth Service (`8001`) terminal** and copy the 6-digit `<OTP_CODE>`.
- **Demo negative test:** Send `{"email": "test@yahoo.com"}` → `403 CORPORATE_EMAIL_REQUIRED`. Send again within 60s → `429 OTP_RATE_LIMITED`.

### 1.2 `POST /api/v1/auth/company/verify`
- **Auth:** None (public)
- **Body:**
  ```json
  {
    "email": "employee@company.com",
    "code": "<OTP_CODE>"
  }
  ```
- **Where values come from:** Same email as step 1.1 + `<OTP_CODE>` from the `8001` terminal.
- **Expected (`200 OK`):** Returns `access_token`, `expires_in` (`900`), `user` (`id`, `email`, `name`), AND sets HttpOnly `refresh_token` cookie.
- **Save:** Copy `access_token` as `<ACCESS_TOKEN>`.

### 1.3 `GET /api/v1/auth/google`
- **Auth:** None (public)
- **How to test:** Open **`http://127.0.0.1:8001/api/v1/auth/google`** (or `:8000` if redirect URI is set to `:8000`) **directly in your browser address bar** (not Swagger Execute, because Google blocks CORS `fetch`).
- **Expected:** `302 Redirect` to Google Sign-In + sets `oauth_state` cookie.

### 1.4 `GET /api/v1/auth/google/callback`
- **Auth:** Automatic (Google redirects here with `?code=...&state=...`).
- **Expected:** Validates state & corporate domain, auto-links to existing `users` row if email matches, sets `refresh_token` cookie, redirects `302` to `FRONTEND_AUTH_SUCCESS_URL` (`localhost:3000/auth/callback`).

### 1.5 `GET /api/v1/users/me`
- **Auth:** `Authorization: Bearer <ACCESS_TOKEN>` (Swagger **Authorize 🔒** or header)
- **Body:** None
- **Expected (`200 OK`):**
  ```json
  { "id": "<user-uuid>", "email": "employee@company.com", "name": null }
  ```

### 1.6 `POST /api/v1/auth/refresh`
- **Auth:** Automatic browser `refresh_token` HttpOnly cookie (from step 1.2 or 1.4).
- **Body:** None
- **Expected (`200 OK`):** Returns a brand-new `access_token` AND rotates the `refresh_token` cookie (old refresh token is revoked).

### 1.7 `POST /api/v1/auth/logout`
- **Auth:** Automatic browser `refresh_token` cookie.
- **Body:** None
- **Expected (`200 OK`):** `{"message": "Logged out successfully"}` and revokes/clears the refresh cookie. Calling `/refresh` afterward returns `401 UNAUTHENTICATED`.

---

## 2. Vehicle Service (5 APIs — Port `8002`, via Gateway `8000`)

All 5 endpoints require `Authorization: Bearer <ACCESS_TOKEN>`.

### 2.1 `POST /api/v1/vehicles`
- **Body:**
  ```json
  {
    "vehicle_number": "mh 12-ab 1234",
    "vehicle_type": "CAR",
    "is_ev": true
  }
  ```
- **Allowed `vehicle_type`:** `"CAR"` or `"BIKE"`. (`vehicle_number` is auto-normalized to `"MH12AB1234"`.)
- **Expected (`201 Created`):** Returns vehicle with `id` → **save as `<VEHICLE_ID>`**.
- **Demo negative test:** Submit the same plate again → `409 VEHICLE_ALREADY_REGISTERED`.

### 2.2 `GET /api/v1/vehicles`
- **Body:** None
- **Expected (`200 OK`):** `{"vehicles": [ ...your active vehicles... ]}`.

### 2.3 `GET /api/v1/vehicles/{vehicle_id}`
- **Path param:** `vehicle_id` = `<VEHICLE_ID>` (from step 2.1).
- **Expected (`200 OK`):** Single vehicle object. Random UUID or another user's vehicle → `404 VEHICLE_NOT_FOUND`.

### 2.4 `PUT /api/v1/vehicles/{vehicle_id}`
- **Path param:** `vehicle_id` = `<VEHICLE_ID>`.
- **Body (full update — all 3 fields required):**
  ```json
  {
    "vehicle_number": "MH12AB9999",
    "vehicle_type": "CAR",
    "is_ev": true
  }
  ```
- **Behind the scenes:** Calls Parking Service (`8003`) to check blocking bookings.
- **Expected:** `200 OK` if no blocking booking; `409 VEHICLE_HAS_BLOCKING_BOOKING` if vehicle has an active/future `CONFIRMED` or unexpired `PAYMENT_PENDING` booking; `503` if Parking Service is stopped.

### 2.5 `DELETE /api/v1/vehicles/{vehicle_id}`
- **Path param:** `vehicle_id` = `<VEHICLE_ID>`.
- **Body:** None (soft deactivation: sets `is_active = false`).
- **Expected:** `200 OK` (`{"id": "...", "is_active": false, "message": "Vehicle removed successfully"}`), or `409 VEHICLE_HAS_BLOCKING_BOOKING` if a booking depends on it.

---

## 3. Parking Service — Public APIs (5 APIs — Port `8003`, via Gateway `8000`)

All 5 endpoints require `Authorization: Bearer <ACCESS_TOKEN>`.

### 3.1 `GET /api/v1/parking/availability`
- **Query parameters:**
  - `date` = `<DATE>` (today or tomorrow, not Sunday, `YYYY-MM-DD`)
  - `start_time` = `10:00` (whole hour, `07:00`–`21:00`)
  - `end_time` = `12:00` (whole hour, `<= 22:00`, max 12h duration)
  - `vehicle_id` = `<VEHICLE_ID>` (from step 2.1)
  - `requires_charging` = `true` (only allowed if vehicle has `is_ev: true`; otherwise `422 CHARGING_NOT_SUPPORTED`)
- **Example URL:**
  ```text
  http://127.0.0.1:8000/api/v1/parking/availability?date=2026-11-24&start_time=10:00&end_time=12:00&vehicle_id=<VEHICLE_ID>&requires_charging=true
  ```
- **Expected (`200 OK`):** `available`, `available_slots`, `rate_per_hour` (`20.00` with charging, `10.00` without).

### 3.2 `POST /api/v1/parking/bookings`
- **Required Headers:**
  - `Authorization: Bearer <ACCESS_TOKEN>`
  - `Idempotency-Key: <IDEMPOTENCY_KEY>` (generate a fresh UUID, e.g. `11111111-1111-4111-8111-111111111111`)
- **Body:**
  ```json
  {
    "vehicle_id": "<VEHICLE_ID>",
    "date": "<DATE>",
    "start_time": "10:00",
    "end_time": "12:00",
    "requires_charging": true
  }
  ```
- **Expected (`201 Created`):** Auto-allocates a compatible slot (e.g. `C51`), calculates `amount` (`40.00`), creates 5-min `PAYMENT_PENDING` hold, stores vehicle snapshots, and calls Payment Service to create a `PENDING` payment.
- **Save:** Copy `booking_id` (`<BOOKING_ID>`) and `payment_id` (`<PAYMENT_ID>`).
- **Demo tests to try:**
  - Re-send exact same request + same `Idempotency-Key` → `200 OK` (returns same booking, no duplicate!).
  - Re-send same `Idempotency-Key` with `end_time: "13:00"` → `409 IDEMPOTENCY_CONFLICT`.
  - Send new `Idempotency-Key` with overlapping time (`11:00`–`13:00`) → `409 USER_BOOKING_OVERLAP`.

### 3.3 `GET /api/v1/parking/bookings`
- **Query parameters (optional):** `page=1&page_size=20`
- **Expected (`200 OK`):** Paginated list `{items, page, page_size, total_items}` (lazily flips any expired `PAYMENT_PENDING` holds to `EXPIRED`).

### 3.4 `GET /api/v1/parking/bookings/{booking_id}`
- **Path param:** `booking_id` = `<BOOKING_ID>` (from step 3.2).
- **Expected (`200 OK`):** Full booking details including `status` (`PAYMENT_PENDING` before payment, `CONFIRMED` after payment, `CANCELLED` after cancel, `EXPIRED` after failure/timeout).

### 3.5 `POST /api/v1/parking/bookings/{booking_id}/cancel`
- **Path param:** `booking_id` = `<BOOKING_ID>` (must be `CONFIRMED` and strictly `> 5 min` before `start_time`).
- **Body:** None
- **Expected (`200 OK`):** `{"booking_id": "...", "status": "CANCELLED", "cancelled_at": "..."}`.
- **Demo negative test:** Try cancelling while still `PAYMENT_PENDING` → `409 BOOKING_NOT_CANCELLABLE`.

---

## 4. Payment Service — Public APIs (2 APIs — Port `8004`, via Gateway `8000`)

Both endpoints require `Authorization: Bearer <ACCESS_TOKEN>`.

### 4.1 `POST /api/v1/payments/{payment_id}/process`
- **Path param:** `payment_id` = `<PAYMENT_ID>` (from step 3.2).
- **Body:**
  ```json
  {
    "payment_method": "UPI"
  }
  ```
  *(Allowed values: `"UPI"`, `"CARD"`, `"WALLET"`. Never send `status` — outcome is backend-controlled!)*
- **Optional Test Header (dev only):**
  - Omit header → uses `PAYMENT_SIMULATION_DEFAULT_OUTCOME` (`SUCCESS`).
  - Add `X-Test-Payment-Outcome: FAILED` → forces a simulated failure (`status: "FAILED"`, `transaction_id: null`, and Parking transitions booking to `EXPIRED`!).
- **Expected (`200 OK`):**
  ```json
  {
    "payment_id": "<PAYMENT_ID>",
    "booking_id": "<BOOKING_ID>",
    "amount": "40.00",
    "status": "SUCCESS",
    "transaction_id": "TXN..."
  }
  ```
- **Next:** Call `GET /api/v1/parking/bookings/<BOOKING_ID>` (step 3.4) to confirm the booking status automatically became **`CONFIRMED`**!
- **Demo negative test:** Call `/process` a second time on the same `<PAYMENT_ID>` → `409 PAYMENT_ALREADY_PROCESSED`.

### 4.2 `GET /api/v1/payments/{payment_id}`
- **Path param:** `payment_id` = `<PAYMENT_ID>`.
- **Expected (`200 OK`):** Full payment record (`payment_method`, `status`, `transaction_id`, `amount`, `expires_at`, `created_at`).

---

## 5. Internal Service-to-Service APIs (3 APIs — Direct Ports Only!)

> **Important:** These 3 routes are **blocked (`404`)** on the API Gateway (`:8000`). Only test them directly on `:8003` / `:8004` with the matching `X-Internal-Service-Token` header.

| # | Method & Direct URL | Caller | Required Header (`X-Internal-Service-Token`) |
|---|---|---|---|
| 5.1 | `POST http://127.0.0.1:8004/internal/v1/payments` | Parking → Payment | `dev-parking-to-payment-token` |
| 5.2 | `POST http://127.0.0.1:8003/internal/v1/bookings/{booking_id}/payment-result` | Payment → Parking | `dev-payment-to-parking-token` |
| 5.3 | `GET http://127.0.0.1:8003/internal/v1/vehicles/{vehicle_id}/booking-dependency` | Vehicle → Parking | `dev-vehicle-to-parking-token` |

### Sample Bodies for Internal APIs
- **5.1 `POST /internal/v1/payments`:**
  ```json
  {
    "booking_id": "<BOOKING_ID>",
    "user_id": "<USER_UUID>",
    "amount": 40.00,
    "expires_at": "2026-11-24T10:05:00+05:30"
  }
  ```
- **5.2 `POST /internal/v1/bookings/{booking_id}/payment-result`:**
  ```json
  {
    "payment_id": "<PAYMENT_ID>",
    "status": "SUCCESS",
    "transaction_id": "TXN1234567890",
    "processed_at": "2026-11-24T10:02:00+05:30"
  }
  ```
- **5.3 `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency`:** No body → returns `{"has_blocking_booking": true/false, "blocking_booking_count": 0}`.

---

## 6. Quick Gateway Security Check (Demo Highlight)

Run these two PowerShell commands against the **API Gateway (`:8000`)** to prove security enforcement:

```powershell
# 1. Internal route is blocked at Gateway -> 404 NOT_FOUND
curl.exe -i -X POST http://127.0.0.1:8000/internal/v1/payments

# 2. Protected route without JWT is rejected early at Gateway -> 401 UNAUTHENTICATED
curl.exe -i http://127.0.0.1:8000/api/v1/vehicles
```
