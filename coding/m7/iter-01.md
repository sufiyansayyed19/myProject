# Milestone 7 (m7) — Iteration 01: End-to-End, Migration Runner & PostgreSQL Concurrency Tests

## Goal
Verify the entire 5-app platform end-to-end against real PostgreSQL databases, prove our PostgreSQL concurrency/locking guarantees under simultaneous race conditions, and add one-command scripts for migrations and full test execution.

## What Was Built

### 1. Convenience Scripts
- `scripts/migrate_all.ps1` — Runs `alembic upgrade head` independently across all 4 business services (`user_db`, `vehicle_db`, `parking_db` [auto-seeding 100 slots], `payment_db`).
- `scripts/run_all_tests.ps1` — Runs all 8 test suites (4 services + Gateway + PostgreSQL concurrency + full E2E) in isolated processes.

### 2. Real PostgreSQL Concurrency Tests (`tests/test_pg_concurrency.py`)
- **`test_pg_ev_bike_slot_race_no_double_allocation`:** 10 distinct users simultaneously race for the 5 EV-charging bike slots (`B36`–`B40`) in `parking_db` → proves **exactly 5 unique slots allocated** and **5 rejected with `409 NO_PARKING_CAPACITY`** (zero double-allocation via `FOR UPDATE`).
- **`test_pg_same_user_simultaneous_overlap_serialized`:** 1 user fires 4 simultaneous overlapping requests with different vehicles → proves **exactly 1 succeeds** and **3 receive `409 USER_BOOKING_OVERLAP`** (via `pg_advisory_xact_lock`).

### 3. Full End-to-End Multi-Service Journey Test (`tests/test_e2e_journey.py`)
Spins up all 5 FastAPI apps (`gateway` + 4 business services) connected to all 4 real PostgreSQL databases and verifies the complete 10-step journey through the API Gateway:
1. Gateway blocks `/internal/v1/*` (`404`).
2. Register EV car via Gateway → Vehicle Service (`201`).
3. Check availability via Gateway → Parking → Vehicle (`200`, `₹20/hr`).
4. Create booking via Gateway → Parking → Vehicle + Payment (`201`, `PAYMENT_PENDING`, `₹40`).
5. Vehicle delete blocked (`409 VEHICLE_HAS_BLOCKING_BOOKING`) while hold is active.
6. Process simulated UPI payment via Gateway → Payment → internal callback to Parking (`200 SUCCESS`).
7. Booking transitions to `CONFIRMED`.
8. Vehicle delete still blocked (`409`) while future confirmed booking exists.
9. Cancel confirmed booking (`200 CANCELLED`).
10. Vehicle soft-deactivation now succeeds (`200`, `is_active = false`).

## How to Run Everything
```powershell
.\scripts\migrate_all.ps1
.\scripts\run_all_tests.ps1
```
