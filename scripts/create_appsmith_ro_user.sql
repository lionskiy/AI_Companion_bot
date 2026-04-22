-- Read-only PostgreSQL user for Appsmith dashboard
-- Run once against the mirror database:
--   psql $DATABASE_URL -f scripts/create_appsmith_ro_user.sql

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'appsmith_ro') THEN
    CREATE ROLE appsmith_ro WITH LOGIN PASSWORD 'appsmith_ro_change_me';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE mirror TO appsmith_ro;
GRANT USAGE ON SCHEMA public TO appsmith_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO appsmith_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO appsmith_ro;
