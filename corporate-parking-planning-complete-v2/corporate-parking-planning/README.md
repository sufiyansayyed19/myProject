# Corporate Parking Reservation and Management System

## Planning documentation

This folder is the planning and implementation handoff package for the Corporate Parking Reservation and Management System. It is intended to be usable in a separate implementation conversation or IDE workflow without reconstructing decisions from chat history.

**Scope:** product requirements, business rules, architecture, API contracts, PostgreSQL data design, service communication, security, end-to-end workflows, reliability, quality/testing and open decisions. This is a planning package; it contains no application implementation, Dockerfiles, CI/CD pipelines or Kubernetes/AWS configuration.

## How to read this documentation

Read in numbered order. The numbers indicate the recommended reading sequence, not service priority.

| # | File | Purpose | Status |
|---:|---|---|---|
| 00 | `README.md` | Navigation, project summary and document status | Complete |
| 01 | `project-overview.md` | Product purpose, scope, users, assumptions and boundaries | Complete |
| 02 | `business-rules.md` | Booking, availability, vehicle, charging, payment and cancellation rules | Complete |
| 03 | `architecture.md` | Components, service responsibilities, data ownership and architecture views | Complete |
| 04 | `api-auth-service.md` | User/Auth Service API contracts | Complete |
| 05 | `api-vehicle-service.md` | Vehicle Service API contracts | Complete |
| 06 | `api-parking-service.md` | Parking Service API contracts | Complete |
| 07 | `api-payment-service.md` | Payment Service API contracts | Complete |
| 08 | `database-design.md` | PostgreSQL tables, columns, types, constraints, indexes and relationships | Complete |
| 09 | `service-communication-and-security.md` | Service interactions, identity propagation, Gateway and internal security | Complete |
| 10 | `workflows-and-reliability.md` | End-to-end journeys, state transitions, concurrency, expiry and retries | Complete |
| 11 | `quality-and-testing-plan.md` | NFRs, error conventions, security checks and test scenarios | Complete |
| 12 | `decisions-and-open-questions.md` | Approved baseline, proposals, blockers, future scope and implementation handoff | Complete |

**Total: 13 Markdown files (including this README).**

## Project at a glance

The system manages a limited pool of corporate parking spaces. Eligible employees authenticate, register vehicles, check availability, reserve a compatible space, and complete a simulated payment. A booking is confirmed only after successful payment and validation that the temporary slot hold is still valid.

### Current service inventory

| Component | Type | Primary responsibility |
|---|---|---|
| API Gateway | Infrastructure component | Single frontend entry point, routing and common request handling |
| User/Auth Service | Business microservice | Corporate-email OTP verification and authentication |
| Vehicle Service | Business microservice | Registered vehicle records |
| Parking Service | Business microservice | Availability, slot allocation, bookings, cancellation and fee calculation |
| Payment Service | Business microservice | Simulated payment lifecycle and result notification |

The Session Service was deliberately removed. The current business model prices the reservation by booked duration and has no physical check-in/check-out, overstay, no-show or actual-use billing workflow.

## API inventory count

The baseline contains **20 operations**, counting both public and internal operations (Google OAuth was dropped in favor of purely corporate-email OTP authentication):

| Service | Operations | Notes |
|---|---:|---|
| User/Auth | 5 | Company send-code, company verify, users/me, logout, refresh |
| Vehicle | 5 | Create, list, get, update and deactivate |
| Parking | 7 | Five user-facing operations, Payment result callback, and Vehicle booking-dependency check |
| Payment | 3 | Internal payment creation plus two user-facing operations |
| **Total** | **20** | |

The Payment creation route is documented as `POST /internal/v1/payments` because Parking Service is the caller; it is not a frontend operation. Both `POST /internal/v1/bookings/{booking_id}/payment-result` and `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency` are internal Parking-owned endpoints.

Both approved extensions (`POST /api/v1/auth/refresh` and `GET /internal/v1/vehicles/{vehicle_id}/booking-dependency`) are included, while Google OAuth (`/api/v1/auth/google` and `/api/v1/auth/google/callback`) was removed from scope.

## Decision-status vocabulary

- **Agreed** — explicitly settled in planning.
- **Proposed** — recommended but not explicitly accepted.
- **Open** — needs a decision before the affected implementation work.
- **Future scope** — intentionally excluded from the current implementation.

The document `decisions-and-open-questions.md` is the consolidated register. Do not treat an example or recommendation as approval.

## Baseline constraints

- PostgreSQL is the agreed database technology.
- The four business services will use Python + FastAPI, with SQLAlchemy as the ORM/database-access layer for PostgreSQL.
- Current scope has four business microservices; Gateway is infrastructure, not a business microservice.
- Each service owns its data. Cross-service references are identifiers, not cross-database foreign keys.
- No service reads or writes another service's database directly.
- Payment is simulated for the current project; real provider integration is future scope.
- No Kafka/RabbitMQ, Session Service, physical parking hardware, actual occupancy detection or kWh billing in current scope.
- The business-service stack is agreed: Python + FastAPI + synchronous SQLAlchemy (`Session`) + `psycopg` (v3) + Alembic + PostgreSQL (four separate databases: `user_db`, `vehicle_db`, `parking_db`, `payment_db`).
- Repository layout is agreed as a monorepo: `services/user-auth-service`, `services/vehicle-service`, `services/parking-service`, `services/payment-service`, and `gateway/`.
- The API Gateway is agreed as a lightweight FastAPI reverse proxy (infrastructure only; no business logic or database).

## Agreed implementation technology baseline

- **Repository layout:** Monorepo with `services/user-auth-service`, `services/vehicle-service`, `services/parking-service`, `services/payment-service`, and `gateway/`.
- **API Gateway:** Lightweight FastAPI reverse proxy (routing, auth validation, CORS, request-level concerns; never exposes `/internal/v1/*` and strips externally supplied internal auth headers).
- **Language:** Python for the four business services.
- **Web framework:** FastAPI with synchronous route handlers (`def`) for database operations.
- **Persistence/ORM:** Synchronous SQLAlchemy (`Session`) with `psycopg` (v3) PostgreSQL driver, provided via request-scoped FastAPI dependencies.
- **Migrations:** Independent Alembic configuration and migration history per service.
- **Database:** PostgreSQL with four separately owned databases (`user_db`, `vehicle_db`, `parking_db`, `payment_db`) and separate credentials/roles per service.

SQLAlchemy engines, session factories, declarative metadata, ORM models and Alembic migration histories remain service-local. No shared ORM models, shared migration histories, or cross-service database access are permitted.

## Planning iterations

- **Iteration 1 — Project foundation:** overview, business rules and architecture.
- **Iteration 2 — Technical design:** four service API contracts and PostgreSQL data model.
- **Iteration 3 — Integration and handoff:** service communication/security, workflows/reliability, quality/testing and decision register.

All three documentation iterations are now complete. This does not mean every technical decision is finalized: the remaining blockers are explicitly captured in the decision register. The next work belongs in a separate implementation session or IDE after resolving the remaining decisions that affect the first implementation slice. The business-service stack is already selected as Python + FastAPI + SQLAlchemy + PostgreSQL.

## Suggested reading order for a new implementation session

1. Read `README.md`, `project-overview.md`, `business-rules.md` and `architecture.md` for context.
2. Read the four `api-*-service.md` documents and `database-design.md` for contracts/data ownership.
3. Read `service-communication-and-security.md` and `workflows-and-reliability.md` before implementing integration/concurrency.
4. Read `quality-and-testing-plan.md` to define acceptance tests.
5. Read `decisions-and-open-questions.md` and resolve its blocker items before coding affected features.

The planning owner should update the relevant source document and decision register when a decision is made. Keep this README's index synchronized when files are added or renamed.
