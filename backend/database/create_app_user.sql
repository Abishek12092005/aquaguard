-- ===========================================================================
-- AquaGuard AI — application user provisioning
-- ===========================================================================
-- Run this ONLY as a MySQL administrator (root), if you need to create the
-- application login. schema.sql deliberately does not create users or grants,
-- so it stays runnable by a non-administrative account.
--
--   mysql -u root -p < database/create_app_user.sql
--
-- IMPORTANT: the password is NOT hardcoded in this file. Pass it as a
-- user-defined variable, or let MySQL prompt is not available here — so use
-- the variable form below and supply the value on the command line:
--
--     mysql -u root -p --init-command="SET @app_password='your-strong-pass'" \
--           < database/create_app_user.sql
--
-- Never commit a real password into a .sql file: unlike .env it is not
-- git-ignored, so it would go straight into version control history where it
-- cannot be removed by a later commit.
--
-- Why not just use root?
--   Flask connecting as root means a single SQL injection or leaked .env hands
--   over the entire MySQL server — every other schema, plus user management.
--   This account can only read and write rows in aquaguard_db. It cannot drop
--   tables, alter schemas, or see anything else on the server.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- The application account
-- ---------------------------------------------------------------------------
SET @app_password = IFNULL(@app_password, '');

-- Refuse to run with no password rather than quietly creating a blank one.
SET @msg = IF(@app_password = '',
  'ERROR: Set @app_password before running this file. See the header comment.',
  CONCAT('Creating aquaguard_ai with a ', LENGTH(@app_password), '-character password'));
SELECT @msg AS status;

-- The password is interpolated at runtime through a prepared statement.
-- It is never written into this file, so nothing sensitive reaches git.
SET @ddl = CONCAT(
  'CREATE USER IF NOT EXISTS ''aquaguard_ai''@''localhost'' IDENTIFIED BY ''',
  @app_password, '''');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = CONCAT(
  'CREATE USER IF NOT EXISTS ''aquaguard_ai''@''127.0.0.1'' IDENTIFIED BY ''',
  @app_password, '''');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Re-running the file should also update the password, not just no-op.
SET @ddl = CONCAT(
  'ALTER USER ''aquaguard_ai''@''localhost'' IDENTIFIED BY ''', @app_password, '''');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = CONCAT(
  'ALTER USER ''aquaguard_ai''@''127.0.0.1'' IDENTIFIED BY ''', @app_password, '''');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- DML only: SELECT, INSERT, UPDATE, DELETE.
-- Notably absent: DROP, ALTER, CREATE, GRANT, FILE.
GRANT SELECT, INSERT, UPDATE, DELETE ON `aquaguard_db`.* TO 'aquaguard_ai'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON `aquaguard_db`.* TO 'aquaguard_ai'@'127.0.0.1';

FLUSH PRIVILEGES;

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
SELECT
  User,
  Host,
  IF(Super_priv = 'Y', 'ADMIN', 'restricted') AS privilege_level
FROM mysql.user
WHERE User = 'aquaguard_ai';

SHOW GRANTS FOR 'aquaguard_ai'@'localhost';
