# Corporate Parking Reservation System — Coding Progress

> Master tracker for the milestone-by-milestone build. Read this file first in any fresh session.

## Service Map & Local Ports

| Component | Path | Local Port | PostgreSQL DB | DB Role |
|---|---|---:|---|---|
| API Gateway | `gateway/` | `8000` | None (infrastructure only) | — |
| User/Auth Service | `services/user-auth-service/` | `8001` | `user_db` | `user_auth_user` |
| Vehicle Service | `services/vehicle-service/` | `8002` | `vehicle_db` | `vehicle_user` |
| Parking Service | `services/parking-service/` | `8003` | `parking_db` | `parking_user` |
| Payment Service | `services/payment-service/` | `8004` | `payment_db` | `payment_user` |

## Milestones

| Milestone | Scope | Status | Log |
|---|---|---|---|
| **m0** | Finalize planning & sprint-demo decisions | Done | [m0/iter-01.md](m0/iter-01.md) |
| **m1** | Monorepo scaffold, DB init SQL, Alembic per service, dev RSA keygen, `/health` | Done (iter-01) | [m1/iter-01.md](m1/iter-01.md) |
| **m2** | User/Auth Service (7 APIs: OTP, Google OAuth + linking, RS256 JWT + refresh) | Done (iter-01) | [m2/iter-01.md](m2/iter-01.md) |
| **m3** | Vehicle Service (5 APIs: owner-scoped CRUD, soft delete, plate normalization) | Pending | `m3/` |
| **m4** | Parking Service Core (5 public APIs: availability, booking + locking + idempotency, history, cancel) | Pending | `m4/` |
| **m5** | Payment Service (3 APIs) + Parking Internal APIs (callback + vehicle dependency check) | Pending | `m5/` |
| **m6** | API Gateway (`gateway/` reverse proxy, early JWT validation, CORS, header stripping) | Pending | `m6/` |
| **m7** | End-to-End, Time-Boundary & Concurrency Tests | Pending | `m7/` |
