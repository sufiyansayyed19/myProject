-- Initialize four isolated PostgreSQL databases and service roles
-- Run as a PostgreSQL superuser, e.g.:
--   psql -U postgres -f scripts/init_postgres.sql

-- 1. Create dedicated roles (change passwords in non-local environments)
CREATE ROLE user_auth_user WITH LOGIN PASSWORD 'user_auth_pass';
CREATE ROLE vehicle_user   WITH LOGIN PASSWORD 'vehicle_pass';
CREATE ROLE parking_user   WITH LOGIN PASSWORD 'parking_pass';
CREATE ROLE payment_user   WITH LOGIN PASSWORD 'payment_pass';

-- 2. Create four separately owned databases
CREATE DATABASE user_db    OWNER user_auth_user;
CREATE DATABASE vehicle_db OWNER vehicle_user;
CREATE DATABASE parking_db OWNER parking_user;
CREATE DATABASE payment_db OWNER payment_user;

-- 3. Restrict cross-database connections
REVOKE CONNECT ON DATABASE user_db    FROM PUBLIC;
REVOKE CONNECT ON DATABASE vehicle_db FROM PUBLIC;
REVOKE CONNECT ON DATABASE parking_db FROM PUBLIC;
REVOKE CONNECT ON DATABASE payment_db FROM PUBLIC;

GRANT CONNECT ON DATABASE user_db    TO user_auth_user;
GRANT CONNECT ON DATABASE vehicle_db TO vehicle_user;
GRANT CONNECT ON DATABASE parking_db TO parking_user;
GRANT CONNECT ON DATABASE payment_db TO payment_user;
