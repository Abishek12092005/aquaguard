-- ===========================================================================
-- AquaGuard AI — test database provisioning
-- ===========================================================================
-- Run this ONCE as a MySQL administrator, on a machine where the test suite
-- needs to run.
--
-- WHY IT IS NEEDED. `create_app_user.sql` grants `aquaguard_ai` DML rights on
-- `aquaguard_db` only. The test configuration connects to `aquaguard_db_test`
-- (see `TestingConfig.SQLALCHEMY_DATABASE_URI`), and without the grant every
-- request in the suite fails with:
--
--     (1044, "Access denied for user 'aquaguard_ai'@'localhost'
--            to database 'aquaguard_db_test'")
--
-- which surfaces as a 500 on the first fixture that touches the database — an
-- error that looks like a broken route rather than a missing grant.
--
-- This is deliberately a separate file from `create_app_user.sql`. Granting a
-- production account rights on a test database is not something that should
-- happen as a side effect of setting up the application account.
--
--   mysql -u root -p < database/create_test_database.sql
--
-- The password is supplied the same way as in `create_app_user.sql` and is never
-- written into this file:
--
--   mysql -u root -p --init-command="SET @app_password='your-strong-pass'" \
--         < database/create_test_database.sql
-- ===========================================================================

SET @app_password = IFNULL(@app_password, '');
SET @msg = IF(@app_password = '',
  'ERROR: Set @app_password before running this file. See the header comment.',
  'Provisioning the test database and its grants');
SELECT @msg AS status;

-- ---------------------------------------------------------------------------
-- 1. The database itself
-- ---------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS `aquaguard_db_test`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 2. The schema
-- ---------------------------------------------------------------------------
-- IMPORTANT: this file does NOT read `schema.sql`. MySQL cannot `SOURCE` a file
-- from inside a script with a relative path reliably, and a half-applied schema
-- is worse than none. Apply the schema first, as an administrator:
--
--   mysql -u root -p aquaguard_db_test < database/schema.sql
--
-- Then run this file for the grants. The tables added after the original schema
-- (login_events, admin_settings) are in `schema.sql` as well, so a fresh
-- provision gets them; an existing test database gets them from
-- `add_console_tables.py --database aquaguard_db_test`.

-- ---------------------------------------------------------------------------
-- 3. Grants
-- ---------------------------------------------------------------------------
-- DML only, exactly as on the production database. Notably absent: DROP and
-- ALTER, which is why a schema change to the test database needs an
-- administrator — the same constraint the application runs under.
--
-- The CREATE grant IS included here, and only here. The test suite provisions its
-- own tables on first run (`db.create_all()`), so without CREATE the suite cannot
-- prepare itself. This account can never reach the production database, so the
-- wider grant is scoped to a database that holds no real data.
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, REFERENCES
  ON `aquaguard_db_test`.* TO 'aquaguard_ai'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, REFERENCES
  ON `aquaguard_db_test`.* TO 'aquaguard_ai'@'127.0.0.1';

FLUSH PRIVILEGES;

-- ---------------------------------------------------------------------------
-- 4. Verify
-- ---------------------------------------------------------------------------
SELECT
  schema_name AS provisioned_schema
FROM information_schema.schemata
WHERE schema_name = 'aquaguard_db_test';

SHOW GRANTS FOR 'aquaguard_ai'@'localhost';
