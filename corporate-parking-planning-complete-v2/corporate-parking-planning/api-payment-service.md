# Payment Service API Contract

**Document status:** Technical design baseline for simulated payments. The service owns payment records and outcomes; it does not calculate parking fees or update Parking data directly.

## 1. Responsibilities and boundaries

Payment Service:
- creates one payment attempt for a booking using the amount supplied by Parking Service;
- simulates payment success or failure;
- allows an authenticated user to retrieve their own payment details;
- reports final results to Parking Service through an internal callback;
- retries callback delivery when necessary.

It does not calculate fees, allocate slots, own booking status, collect real card/UPI credentials, or integrate a real gateway in the current project.

## 2. Endpoint inventory and access

| Method | Endpoint | Caller | Exposure |
|---|---|---|---|
| POST | `/internal/v1/payments` | Parking Service | Internal only; not Gateway-routed |
| POST | `/api/v1/payments/{payment_id}/process` | Authenticated frontend user | Public via Gateway |
| GET | `/api/v1/payments/{payment_id}` | Authenticated frontend user | Public via Gateway |

The earlier discussion listed `POST /api/v1/payments` as a payment-creation route, but also explicitly established that Parking Service—not the frontend—creates payments. This document therefore recommends making it `/internal/v1/payments`. This is a route exposure/consistency refinement, not an additional business operation.

Payment-result callback is an outbound Payment-to-Parking call, not an endpoint owned by Payment Service:

```http
POST /internal/v1/bookings/{booking_id}/payment-result
```

## 3. Payment representation

```json
{
  "payment_id": "<payment-uuid>",
  "booking_id": "<booking-uuid>",
  "amount": 60.00,
  "payment_method": "UPI",
  "status": "PENDING",
  "transaction_id": null,
  "expires_at": "2026-11-24T14:35:00+05:30",
  "created_at": "2026-11-24T14:30:00+05:30"
}
```

`payment_method` and `transaction_id` may be null before processing. `user_id` is stored for ownership checks but need not be returned.

## 4. Internal `POST /internal/v1/payments`

### Caller

Parking Service only. It is not a frontend API and must not be routed by the public Gateway.

### Request

```json
{
  "booking_id": "<booking-uuid>",
  "user_id": "<user-uuid>",
  "amount": 60.00,
  "expires_at": "2026-11-24T14:35:00+05:30"
}
```

The values originate from Parking's committed booking record. The frontend cannot choose the amount, user ID, or expiry.

### Validation

- Authenticate the internal Parking caller.
- Require a valid booking ID and user ID.
- Require `amount > 0` and a valid expiry.
- Create no more than one payment record per booking.
- Do not recalculate the parking fee.

### Idempotency

Because Parking may retry after a network timeout, creation must be idempotent by `booking_id`:

- if no payment exists, create one and return it;
- if a payment already exists for the same booking and the material request values match, return that existing payment;
- if the same booking ID is presented with a conflicting amount/user/expiry, return a conflict and do not overwrite the original payment.

A unique database constraint on `booking_id` backs this rule.

### Response

`201 Created` for newly created payment; `200 OK` for an idempotent replay returning the existing payment.

```json
{
  "payment_id": "<payment-uuid>",
  "booking_id": "<booking-uuid>",
  "amount": 60.00,
  "status": "PENDING",
  "expires_at": "2026-11-24T14:35:00+05:30"
}
```

### Errors

- `400/422 INVALID_PAYMENT_REQUEST` — malformed amount/expiry or missing identifiers.
- `401/403 INTERNAL_CALLER_UNAUTHORIZED` — caller not trusted.
- `409 PAYMENT_REQUEST_CONFLICT` — an existing booking payment has inconsistent immutable details.

## 5. `POST /api/v1/payments/{payment_id}/process`

### Purpose

Process a simulated payment selected by the authenticated user.

### Request

```json
{
  "payment_method": "UPI"
}
```

Allowed simulated methods: `UPI`, `CARD`, `WALLET`.

No actual card number, CVV, UPI PIN, bank credential, or wallet secret is accepted or stored.

### Authorization

The payment must belong to the authenticated user. Payment Service checks its own `user_id` field against the authenticated identity.

### Processing

1. Load and lock the payment record.
2. Verify ownership.
3. Require `status=PENDING`.
4. Require current time to be before `expires_at`.
5. Validate the simulated payment method.
6. Determine the result using backend-controlled simulation logic.
7. Persist the final result and any simulated transaction reference.
8. Schedule/attempt the callback to Parking Service.
9. Return the payment result.

The frontend cannot send `status=SUCCESS` or `status=FAILED`.

### Simulation strategy — Agreed

The result is **deterministic and backend-controlled**:
- Do not let the frontend submit `status: SUCCESS` or `status: FAILED`.
- Use an environment-controlled default, e.g., `PAYMENT_SIMULATION_DEFAULT_OUTCOME=SUCCESS`, so demonstrations are predictable.
- For automated/manual testing, permit a deterministic test override header such as `X-Test-Payment-Outcome: FAILED` **only** when a non-production test-override setting is explicitly enabled (must be disabled in production).
- Do not rely on random-only payment outcomes.
- `UPI`, `CARD`, and `WALLET` remain simulated payment methods; no actual financial information is collected.

### Success response

```json
{
  "payment_id": "<payment-uuid>",
  "booking_id": "<booking-uuid>",
  "amount": 60.00,
  "status": "SUCCESS",
  "transaction_id": "TXN83921"
}
```

### Failure response

```json
{
  "payment_id": "<payment-uuid>",
  "booking_id": "<booking-uuid>",
  "amount": 60.00,
  "status": "FAILED",
  "transaction_id": null
}
```

The result is final for that payment. The user cannot retry the same booking/payment; a new booking is required under the current business rule. A successful process response confirms the simulated payment result was stored; it does not by itself prove that Parking has already confirmed the booking. The frontend should obtain the booking status from Parking Service.

### Errors

| HTTP | Example code | Meaning |
|---:|---|---|
| 401 | `UNAUTHENTICATED` | No valid application token |
| 404 | `PAYMENT_NOT_FOUND` | Payment doesn't exist or isn't owned by caller |
| 409 | `PAYMENT_ALREADY_PROCESSED` | Payment is already `SUCCESS` or `FAILED` |
| 409 | `PAYMENT_EXPIRED` | Current time is at/after payment expiry |
| 422 | `INVALID_PAYMENT_METHOD` | Method is not supported |

A repeated `/process` request must not create a second simulated transaction. The currently recommended behavior is an explicit `409 PAYMENT_ALREADY_PROCESSED` response; returning the existing outcome is an alternative but should not be mixed across clients.

## 6. `GET /api/v1/payments/{payment_id}`

### Purpose

Retrieve status/details for a payment belonging to the authenticated user.

### Authorization

Payment Service compares stored `user_id` with authenticated `sub`. Do not trust a payment ID alone and do not call Parking for a routine ownership lookup.

### Response

`200 OK`

```json
{
  "payment_id": "<payment-uuid>",
  "booking_id": "<booking-uuid>",
  "amount": 60.00,
  "payment_method": "UPI",
  "status": "SUCCESS",
  "transaction_id": "TXN83921",
  "created_at": "2026-11-24T14:30:00+05:30"
}
```

### Errors

- `401 UNAUTHENTICATED`
- `404 PAYMENT_NOT_FOUND` for nonexistent or non-owned payments.

## 7. Payment state model

```text
PENDING --simulation success--> SUCCESS
PENDING --simulation failure--> FAILED
```

`SUCCESS` and `FAILED` are terminal for the current simulated project. There is no same-payment retry, refund, partial refund, chargeback, or provider settlement state in scope.

## 8. Payment-result callback to Parking

After a final result is durably stored, Payment Service calls:

```http
POST /internal/v1/bookings/{booking_id}/payment-result
```

Request for success:

```json
{
  "payment_id": "<payment-uuid>",
  "status": "SUCCESS",
  "transaction_id": "TXN83921",
  "processed_at": "2026-11-24T14:33:00+05:30"
}
```

Request for failure:

```json
{
  "payment_id": "<payment-uuid>",
  "status": "FAILED",
  "transaction_id": null,
  "processed_at": "2026-11-24T14:33:00+05:30"
}
```

- Authenticate Payment Service as the caller.
- The callback is retried until acknowledged or until an explicitly defined terminal handling policy is reached.
- Parking handles duplicate identical callbacks idempotently.
- Payment Service records callback delivery time/attempt count/next retry time so a transient failure does not lose a successful result.
- Do not introduce Kafka/RabbitMQ solely for this requirement in the current project.

The exact retry schedule, backoff, maximum attempts, and reconciliation policy are not decided in this document; see `workflows-and-reliability.md` and the decision register.

## 9. Expired payment behavior

If `now >= expires_at`, processing is rejected with `409 PAYMENT_EXPIRED`. Parking's booking hold expiry is five minutes. Both services must interpret their expiry timestamps consistently.

A late success must not resurrect an expired booking. In the current simulated system, no refund endpoint is needed; real provider late-success reconciliation/refund is future scope.

## 10. Exclusions

- Real payment gateway integration (including provider SDKs and credentials).
- Real UPI/card/wallet data collection.
- Provider webhooks and signature verification.
- Refunds, settlement, chargebacks, or financial reconciliation.
- Multiple payment attempts for one booking.
- Payment history list endpoint; the current scope retrieves a payment by ID associated with a booking.
