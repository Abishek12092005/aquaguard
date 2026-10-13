-- ===========================================================================
-- AquaGuard AI — remove development seed data
-- ===========================================================================
--   mysql -u root -p aquaguard_db < database/seed_dev_cleanup.sql
--
-- Deletes only the development account created by seed_dev.sql. Every child row
-- (conversations, messages) is removed by ON DELETE CASCADE, so this is a single
-- statement and cannot leave orphans behind.
--
-- water_predictions and alerts are never touched here because seed_dev.sql
-- never writes to them — all rows in those tables are real user data.
-- ===========================================================================

USE `aquaguard_db`;

DELETE FROM `users` WHERE `email` = 'dev@aquaguard.local';

SELECT
  (SELECT COUNT(*) FROM `users`)                  AS remaining_users,
  (SELECT COUNT(*) FROM `water_predictions`)      AS predictions,
  (SELECT COUNT(*) FROM `alerts`)                 AS alerts,
  (SELECT COUNT(*) FROM `aqua_ai_conversations`)  AS conversations,
  (SELECT COUNT(*) FROM `aqua_ai_messages`)       AS messages;
