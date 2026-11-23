# Project Overview

## 1. Project name

**Corporate Parking Reservation and Management System**

## 2. Purpose

The system provides employees with a controlled way to reserve limited corporate parking capacity. It supports registered cars and bikes, distinguishes normal spaces from charging-enabled spaces, allocates compatible spaces automatically, and confirms reservations only after simulated payment succeeds.

The project is also intended to demonstrate sound backend and microservice design: service boundaries, independent data ownership, inter-service APIs, validation, transactional booking allocation, payment lifecycle management, and later DevOps deployment.

## 3. Problem statement

An organization has a limited number of parking spaces and more potential users than spaces. A reservation system is needed to:

- show whether compatible parking capacity is available for a requested time interval;
- let an authenticated employee reserve a space for a registered vehicle;
- avoid assigning the same space to overlapping bookings;
- prevent one user from creating overlapping bookings;
- distinguish charging-enabled reservations from ordinary parking;
- retain booking and payment history.

The project models parking availability from reservation records. It does not claim to detect the physical presence of a vehicle.

## 4. Intended users and actors

### 4.1 Employee/user

An eligible employee can:

- authenticate using the supported corporate identity options;
- register and maintain their vehicles;
- view their registered vehicles;
- check parking availability for a vehicle and time interval;
- create a booking;
- complete the simulated payment flow;
- view their bookings and payment details;
- cancel an eligible confirmed booking.

### 4.2 External identity/delivery providers

- Corporate email delivery provider: delivers one-time verification codes (pluggable interface; console mock in local development).

This is an external dependency, not an internal microservice. Google OAuth is explicitly excluded; authentication is purely corporate-email OTP based.

### 4.3 System services

The Gateway and four business services execute the system's request, identity, vehicle, booking, and payment responsibilities.

## 5. Operating assumptions

These figures and operating policies are **sample project assumptions**, not universal corporate parking standards.

| Item | Baseline assumption |
|---|---|
| Expected users | 500 employees/users |
| Total parking capacity | 100 spaces |
| Car spaces | 60: 50 normal and 10 charging-enabled |
| Bike spaces | 40: 35 normal and 5 charging-enabled |
| Total charging-enabled spaces | 15 |
| Operating hours | 07:00–22:00 |
| Operating days | Monday–Saturday |
| Closed day | Sunday |
| Business timezone | Asia/Kolkata |
| Booking horizon | Today and tomorrow only |
| Maximum booking duration | 12 hours, subject to the 22:00 closing time |

## 6. Product scope

### 6.1 Included in the current scope

- Corporate-domain email OTP verification (sole authentication method; Google OAuth dropped).
- User identity and authenticated profile retrieval.
- Vehicle registration, listing, retrieval, updating and deactivation.
- Vehicle classification: `CAR` or `BIKE`.
- EV attribute on a vehicle.
- Booking-specific charging requirement.
- Availability lookup.
- Automatic compatible-slot allocation.
- Temporary slot holds while payment is pending.
- Booking creation, history, details and cancellation.
- Parking fee calculation using the agreed rate model.
- Simulated payment creation and processing.
- Payment result communication to the Parking Service.
- Booking and payment state tracking.

### 6.2 Explicitly outside the current scope

- Physical occupancy sensors, RFID, ANPR or security-staff workflows.
- Actual check-in/check-out or parking sessions.
- No-show detection or penalties.
- Booking extension or modification; the user cancels and creates a new booking instead.
- Waitlists.
- User-selected specific slot numbers; allocation is automatic.
- Visitor parking.
- Admin dashboard/service and advanced analytics.
- Department-based priority policies.
- Monthly subscriptions.
- Actual UPI/card/wallet money movement or a production payment provider.
- kWh-based or dynamic charging-energy billing.
- Notification microservice.

These may be reconsidered as future scope if a real business need is established.

## 7. System boundary

### Inside the system

- Authentication and user identity.
- Registered vehicle data.
- Parking slot inventory.
- Availability calculation.
- Booking validation and allocation.
- Temporary holds and booking state transitions.
- Fee calculation.
- Simulated payment lifecycle.
- Booking/payment information retrieval.

### Outside the system

- Corporate email provider.
- Physical parking infrastructure and vehicle detection.
- Banks, UPI networks and real payment providers.
- Energy meters and charging hardware.
- Security personnel and manual enforcement processes.

## 8. High-level user journey

1. The employee authenticates.
2. The employee registers a vehicle, if one is not already registered.
3. The employee selects a registered vehicle.
4. If it is an EV, the employee indicates whether charging is required for this particular booking.
5. The employee checks availability for an allowed date and time.
6. The employee submits a booking request.
7. Parking validates the request, checks capacity and creates a temporary hold with `PAYMENT_PENDING` status.
8. Payment Service creates and processes a simulated payment.
9. A successful payment result confirms the booking if the hold remains valid. Failure or expiry causes the booking to expire.
10. The employee can view the booking and, subject to the cancellation rule, cancel a confirmed booking.

## 9. Success criteria for the current project

The planned system should demonstrate that:

- users can only access their own vehicles, bookings and payments;
- vehicle and charging requirements determine compatible slot types;
- simultaneous booking attempts cannot reserve the same slot for overlapping periods;
- one user cannot hold overlapping bookings;
- a booking is not confirmed before successful payment;
- a failed or expired payment does not leave a valid reservation;
- booking and payment history is retained;
- each business service owns its data and communicates through APIs rather than directly querying another service's database.

## 10. Agreed implementation technology baseline

The repository is structured as a monorepo containing `services/user-auth-service`, `services/vehicle-service`, `services/parking-service`, `services/payment-service`, and `gateway/`.

The four business services will be developed using:

- **Python** as the programming language.
- **FastAPI** as the web framework, using synchronous route handlers (`def`) for database operations.
- **SQLAlchemy (synchronous `Session`)** as the ORM/database-access layer with the **`psycopg` (v3)** PostgreSQL driver and request-scoped sessions via FastAPI dependencies.
- **Alembic** independently per service for schema migrations.
- **PostgreSQL** with four separately owned databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) and separate database credentials/roles per service.

Each service will define and own its own SQLAlchemy ORM models, metadata, database engine, session lifecycle, Alembic configuration, and migration history. ORM objects and migration histories are not shared between services, and ORM objects are not returned directly as public API contracts; API request/response schemas remain separate.

The **API Gateway** (`gateway/`) will be implemented as a lightweight FastAPI reverse proxy (infrastructure only: routing, authentication validation, CORS, and request-level concerns; no business logic or database).

## 11. Assumptions and remaining open items

Previously open items that are now **Agreed**:
- Synchronous SQLAlchemy (`Session`) with `psycopg` (v3) and synchronous FastAPI handlers (`def`) across all four business services.
- Four separately owned PostgreSQL databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) on one local PostgreSQL server with separate roles/credentials.
- Independent Alembic migrations per service.
- Automatic account linking when verified corporate emails match (requiring verified OTP and Google `email_verified = true` under the configured corporate domain).
- Same-hour booking uses the nominal whole-hour block (`09:00–10:00` at `09:20`) and charges the full one-hour rate without prorating; because `09:00` has passed, it is not cancellable under the strict >5-minute rule.

All pre-implementation blockers are now **Closed** for the sprint demonstration baseline in `decisions-and-open-questions.md` (including concurrency locking, lazy hold expiry, inline payment/callback retries, RS256 15-min JWT + 7-day refresh cookie, `X-Internal-Service-Token` auth, and common error envelope). Only non-blocking deployment polish items remain deferred.
