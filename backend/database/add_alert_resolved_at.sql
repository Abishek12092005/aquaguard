-- ===========================================================================
-- AquaGuard AI — add alerts.resolved_at
-- ===========================================================================
-- The application account (aquaguard_ai) has DML grants only and cannot ALTER a
-- table, so this is the administrator-run form of the same change that
-- `add_alert_resolved_at.py` performs. Run it as root against any database that
-- already holds alert rows — in particular the test database, which
-- `schema.sql` only creates for a fresh install.
--
--   mysql -u root -p < database/add_alert_resolved_at.sql
--   mysql -u root -p aquaguard_db_test < database/add_alert_resolved_at.sql
--
-- Both statements are guarded, so running this twice is a no-op rather than an
-- "Duplicate column name" error.
--
-- WHY THE COLUMN IS NEEDED. "Seen" and "dealt with" are different states, and
-- the notification badge counts only what is still open. Without a dedicated
-- column, resolution had nowhere to live: it was written into a single API
-- response and then vanished, because every later read re-derived the status
-- from `is_read` alone.
-- ===========================================================================

SET @db := DATABASE();

-- ---------------------------------------------------------------------------
-- resolved_at
-- ---------------------------------------------------------------------------
SET @has_column := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = @db
    AND table_name = 'alerts'
    AND column_name = 'resolved_at'
);

SET @sql := IF(@has_column = 0,
  'ALTER TABLE alerts ADD COLUMN resolved_at TIMESTAMP NULL DEFAULT NULL COMMENT ''NULL while open; set when resolved''',
  'SELECT ''alerts.resolved_at already present'' AS skipped');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- Index for the open-alert count
-- ---------------------------------------------------------------------------
-- The bell asks "how many alerts are unread AND unresolved?", and the Resolved
-- filter asks the complement. Both add `resolved_at` to a predicate already
-- keyed on `user_id`, so the index carries the third column too.
SET @has_index := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = @db
    AND table_name = 'alerts'
    AND index_name = 'ix_alerts_user_resolved'
);

SET @sql := IF(@has_index = 0,
  'ALTER TABLE alerts ADD KEY ix_alerts_user_resolved (user_id, resolved_at)',
  'SELECT ''ix_alerts_user_resolved already present'' AS skipped');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
SELECT column_name, column_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = @db AND table_name = 'alerts'
ORDER BY ordinal_position;
