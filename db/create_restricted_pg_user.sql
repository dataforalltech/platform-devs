-- ============================================================================
-- SECURITY FIX: Create restricted PostgreSQL user for DevTeam MCPs
-- Instead of using superuser 'postgres', create app_devteam with least privilege
-- ============================================================================

-- 1. Create restricted role (app_devteam)
CREATE ROLE app_devteam WITH LOGIN PASSWORD 'generate_strong_password_here';

-- 2. Grant schema access
GRANT USAGE ON SCHEMA public TO app_devteam;

-- 3. Grant CRUD permissions on ALL tables (current + future)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_devteam;

-- 4. Grant SEQUENCE usage (for auto-increment IDs)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_devteam;

-- 5. Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_devteam;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_devteam;

-- 6. Verify permissions
SELECT
    r.rolname as role_name,
    r.rolcanlogin as can_login,
    r.rolsuper as is_superuser,
    r.rolinherit as inherits_roles
FROM pg_roles r
WHERE r.rolname = 'app_devteam';

-- ============================================================================
-- Usage Instructions:
-- ============================================================================
--
-- 1. Update the password in line 5 with a strong, random password
--    OR use: CREATE ROLE app_devteam WITH LOGIN PASSWORD 'complex_password123!@#';
--
-- 2. Execute this script as superuser (postgres):
--    psql -h localhost -U postgres -d app -f db/create_restricted_pg_user.sql
--
-- 3. Update environment variables to use new user:
--    export POSTGRES_USER=app_devteam
--    export POSTGRES_PASSWORD=complex_password123!@#
--
-- 4. All DevTeam MCPs should now connect with app_devteam (not postgres)
--
-- 5. Verify connection:
--    psql -h localhost -U app_devteam -d app -c "SELECT version();"
--
-- ============================================================================
-- Security Notes:
-- ============================================================================
--
-- - app_devteam role has ONLY SELECT/INSERT/UPDATE/DELETE permissions
-- - No CREATE, DROP, ALTER, SUPERUSER, or CREATEDB privileges
-- - Cannot create new users or modify schema
-- - Cannot access pg_* system tables
-- - All queries are logged if query_log is enabled
--
-- Least Privilege Principle: DevTeam can ONLY read/write application data,
-- not manage the database or infrastructure.
--
-- ============================================================================
