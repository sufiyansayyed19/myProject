# Business Rules

This document records the product rules that govern vehicle registration, availability, bookings, slot allocation, pricing, payment and cancellation.

Labels:
- **Agreed** — explicitly settled in planning.
- **Open** — needs a more precise decision before implementation.

## 1. Organization and capacity

**Agreed** sample operating model:

| Resource | Count | Breakdown |
|---|---:|---|
| All spaces | 100 | 60 car + 40 bike |
| Car spaces | 60 | 50 normal + 10 charging-enabled |
| Bike spaces | 40 | 35 normal + 5 charging-enabled |
| Charging-enabled spaces | 15 | 10 car + 5 bike |

Expected user population: 500.

Slots are individual logical records, such as `C01`–`C60` and `B01`–`B40`. They are initialized as inventory data; a separate Admin Service is not required for the current scope.

## 2. Operating calendar and booking window

**Agreed** rules:

- Business timezone: `Asia/Kolkata`.
- Operating hours: 07:00 through 22:00.
- Operating days: Monday through Saturday.
- Sunday is closed.
- A booking date must be either today's calendar date or tomorrow's calendar date, in the business timezone.
- The booking window is not extended to the next two working days or to a rolling seven-day period.
- If tomorrow is Sunday, tomorrow is not bookable.
- Saturday remains an operating day.
- A date that is Sunday is not bookable, even if it falls inside the today/tomorrow calendar window.

## 3. Booking time and duration

**Agreed** rules:

- Normal advance-booking start and end boundaries use whole-hour times (for example, 09:00–11:00).
- Arbitrary minute boundaries such as 09:15 or 12:40 are not offered for normal advance bookings.
- Maximum booking duration is 12 hours.
- A booking must also end no later than 22:00. The 12-hour cap does not permit a booking to extend past closing time.
- Multiple non-overlapping future bookings by one user are allowed.
- Overlapping bookings by the same user are prohibited.
- Booking modification and extension are not supported. The user must cancel an eligible booking and create a new one.

### 3.1 Minimum advance time

For future whole-hour start times, the booking must be made **strictly more than 15 minutes before** the requested start.

Examples recorded during planning:

| Current time | Requested start | Result |
|---|---|---|
| 08:15 | 09:00 | Allowed by the minimum-advance rule |
| 08:44 | 09:00 | Allowed by the minimum-advance rule |
| 08:45 | 09:00 | Rejected; it is not more than 15 minutes ahead |

### 3.2 Same-hour booking rule

**Agreed policy:**

- During the first 30 minutes of the current hour, the current-hour block may be offered if it is logically available.
- After the first 30 minutes, the current-hour block is no longer offered; the next whole-hour block is used.
- Example: at 09:20, `09:00–10:00` may be offered if available.
- Example: at 09:35 or 09:40, the earliest offered block is `10:00–11:00`.
- A user should not be denied a logically empty current-hour block solely because that hour has started.
- **Agreed representation and billing:** store the nominal whole-hour block (`start_time = 09:00`, `end_time = 10:00`) and charge the full one-hour rate. Do not store `09:20` as the start time and do not prorate this booking.
- **Agreed cancellation consequence:** because the scheduled start time (`09:00`) has already passed, a confirmed same-hour booking cannot be cancelled under the existing rule requiring cancellation strictly more than five minutes before the scheduled start. Do not invent a special cancellation or refund exception.

## 4. Vehicle rules

**Agreed** rules:

- Supported vehicle types are `CAR` and `BIKE`.
- A user can register multiple vehicles.
- A vehicle belongs to one authenticated user.
- Vehicle information is registered once and selected during booking; users do not re-enter full vehicle details for every booking.
- The vehicle stores its type and whether it is an EV.
- `requires_charging` is a booking-level choice, not a permanent property of the vehicle.
- A non-EV cannot request charging.
- A vehicle must be active and owned by the requesting user to be used for a new booking.

### 4.1 Vehicle removal and modification

- **Agreed:** deactivate a vehicle (`is_active = false`) rather than physically delete it, preserving historical booking references.
- **Agreed:** block vehicle updates and deactivation with `409 Conflict` if the vehicle has a blocking booking: a future or currently active `CONFIRMED` booking, or a valid unexpired `PAYMENT_PENDING` booking. Historical, `CANCELLED`, `EXPIRED`, and already-ended bookings do not block mutation. Vehicle Service enforces this by calling Parking Service's internal endpoint `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency`.
- **Agreed:** bookings also capture immutable vehicle snapshots (`vehicle_number_snapshot`, `vehicle_type_snapshot`, `is_ev_snapshot`) at creation time so historical booking records remain accurate even if a vehicle is later modified or deactivated.

## 5. Charging and slot compatibility

**Agreed** compatibility rules:

| Vehicle | Charging requested? | Compatible space |
|---|---|---|
| Non-EV car | No | Normal car space |
| Non-EV car | Yes | Invalid request |
| EV car | No | Normal car space |
| EV car | Yes | Charging-enabled car space |
| Non-EV bike | No | Normal bike space |
| Non-EV bike | Yes | Invalid request |
| EV bike | No | Normal bike space |
| EV bike | Yes | Charging-enabled bike space |

The vehicle type must match the slot's vehicle type. If charging is required, the slot must be charging-enabled.

The user does not choose a specific slot. Parking Service selects a compatible available slot automatically. If no compatible capacity exists, the booking is rejected; there is no waitlist.

## 6. Availability rules

- Availability lookup is informational only; it does not reserve capacity.
- Availability is calculated from slot inventory and overlapping bookings/valid temporary holds.
- `CANCELLED` and `EXPIRED` bookings do not block availability.
- A `PAYMENT_PENDING` booking blocks its selected slot while its hold is valid.
- A successful booking transaction is the authority for slot allocation. The result of an earlier availability query is not a guarantee.
- No physical sensor or occupancy flag is used to determine software availability.

Two time intervals overlap when:

`new_start < existing_end AND new_end > existing_start`

Intervals that meet exactly at a boundary do not overlap. For example, 09:00–10:00 and 10:00–11:00 are non-overlapping.

## 7. User-level booking conflict

A user cannot have two overlapping bookings, even if the bookings would use different slots or vehicles.

The overlap check applies to bookings that are still operationally active, including confirmed bookings and payment-pending bookings whose holds remain valid. Cancelled and expired bookings do not block a new booking.

The exact treatment of a stale `PAYMENT_PENDING` row whose hold expiry timestamp has passed is handled by the booking-expiry/reconciliation design; it must not block capacity indefinitely.

## 8. Temporary holds and booking state

**Agreed** rules:

- Booking creation atomically allocates a compatible slot and creates a `PAYMENT_PENDING` booking.
- The temporary hold lasts five minutes.
- A valid payment success received before hold expiry changes the booking to `CONFIRMED`.
- Payment failure or timeout causes the booking to become `EXPIRED` and its slot to become available through derived availability.
- A late success after hold expiry must not resurrect an expired booking.
- There is no separate Hold Service or slot-release endpoint.
- Booking status, hold expiry and slot-conflict queries determine availability.

Current lifecycle:

```text
PAYMENT_PENDING --success while hold valid--> CONFIRMED
PAYMENT_PENDING --failure/timeout/hold expiry--> EXPIRED
CONFIRMED --eligible user cancellation--> CANCELLED
```

No `ALLOCATED`, `RELEASED` or `COMPLETED` state is currently required.

## 9. Pricing

**Agreed** rates:

| Booking category | Rate |
|---|---:|
| Normal parking, including an EV not requesting charging | ₹10 per hour |
| EV booking that requests charging | ₹20 per hour |

The ₹20/hour rate is the total charging-session booking rate, not ₹10 parking plus ₹20 charging.

Examples:

- 3 hours of normal parking: ₹30.
- 3 hours of EV parking with charging: ₹60.

Parking Service calculates the amount. The frontend does not provide an authoritative amount, and Payment Service stores the amount it receives rather than recalculating it.

**Agreed:** all bookings use whole-hour blocks (including the same-hour exception, which stores the nominal whole-hour block and charges the full one-hour rate with no prorating).

## 10. Cancellation

**Agreed** rule:

- A confirmed booking may be cancelled only when the current time is strictly more than five minutes before its start time.
- Example for a 10:00 booking: 09:54 is allowed; 09:55 is not allowed.
- Cancellation changes the booking state to `CANCELLED`; it does not delete the record.
- Cancellation timestamp is retained.
- No separate slot-release API is needed. The cancelled booking no longer blocks availability.

The final API contract must define behavior for cancellation requests against `PAYMENT_PENDING`, `EXPIRED` or already `CANCELLED` bookings.

## 11. Payment rules

**Agreed** current-project scope:

- Payment is simulated; no real money is collected.
- Payment Service owns payment records and payment status.
- Parking Service owns fee calculation and booking status.
- Payment must succeed before a booking becomes confirmed.
- Payment creation is initiated by Parking Service after the hold exists.
- Payment methods may be represented as simulated `UPI`, `CARD` or `WALLET` choices.
- The client cannot submit an arbitrary `SUCCESS` or `FAILED` status.
- Payment failure expires the booking; there is no retry on the same booking. The user creates a new booking to try again.
- One payment attempt per booking is the current model.
- Payment Service reports its result to Parking Service through an internal endpoint.
- Callback delivery must be safely retryable and idempotent.

Real payment-provider integration, provider webhooks, refunds and financial reconciliation are future scope.

## 12. Authentication and access rules

- Company email verification is supported, restricted to a configurable corporate email domain.
- Google OAuth is also in the planned API surface, but the authenticated Google identity must satisfy the corporate-domain policy.
- A domain check models the project's eligibility rule; it is not proof of current employment in a real organization.
- User-owned vehicle, booking and payment operations derive the user identity from authentication, not from a client-supplied `user_id`.
- A user must not access another user's vehicle, booking or payment by guessing an identifier.

Exact token, account-linking and service-authentication mechanics are specified in later design documents and remain subject to the decision register.

## 13. Explicit exclusions

The following are deliberately excluded from current rules and must not be reintroduced without a justified scope change:

- Session/check-in/check-out service.
- Physical occupancy detection.
- Overstay billing or booking extension.
- No-show tracking or penalties.
- Waitlist.
- User-selected slot number.
- Real charging energy measurement or kWh billing.
- Real gateway payment processing.
- Admin, visitor or notification services.
