-- ===========================================================================
-- AquaGuard AI — OPTIONAL development seed data
-- ===========================================================================
-- NOT run by schema.sql. This file is never applied automatically and must be
-- invoked deliberately:
--
--   mysql -u root -p aquaguard_db < database/seed_dev.sql
--
-- To undo it completely:
--
--   mysql -u root -p aquaguard_db < database/seed_dev_cleanup.sql
--
-- What this seeds, and why:
--   * ONE development account, so you can sign in on a fresh machine before
--     the registration flow is verified.
--   * ONE conversation with a short exchange, so the Aqua AI sidebar has a row
--     to render while the chat endpoint is being built.
--
-- What this deliberately does NOT seed:
--   * NO water_predictions and NO alerts.
--
--     Prediction history is the primary thing this project demonstrates. Seeding
--     it would populate the dashboard, charts and history list with numbers that
--     were never produced by the model — exactly the fake data the project
--     forbids. Both tables start genuinely empty; the first real prediction
--     creates the first real row.
--
-- The development password below is a throwaway for local use. It is stored as
-- its bcrypt digest (cost 12), never in plain text. Do not reuse it anywhere.
-- ===========================================================================

USE `aquaguard_db`;

-- ---------------------------------------------------------------------------
-- Development account
-- ---------------------------------------------------------------------------
-- email    : dev@aquaguard.local
-- password : DevPassword123
--
-- The hash below is a real bcrypt digest of that password; the column itself
-- only ever holds the digest.
INSERT INTO `users` (`name`, `email`, `password_hash`, `role`)
SELECT
  'Development User',
  'dev@aquaguard.local',
  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyDPH1nMZ7pO4i',
  'user'
WHERE NOT EXISTS (
  SELECT 1 FROM `users` WHERE `email` = 'dev@aquaguard.local'
);

-- ---------------------------------------------------------------------------
-- One Aqua AI conversation, so the sidebar is not empty
-- ---------------------------------------------------------------------------
INSERT INTO `aqua_ai_conversations` (`user_id`, `title`)
SELECT u.`id`, 'Getting started with AquaGuard AI'
FROM `users` u
WHERE u.`email` = 'dev@aquaguard.local'
  AND NOT EXISTS (
    SELECT 1 FROM `aqua_ai_conversations` c
    WHERE c.`user_id` = u.`id` AND c.`title` = 'Getting started with AquaGuard AI'
  );

INSERT INTO `aqua_ai_messages` (`conversation_id`, `role`, `content`)
SELECT c.`id`, 'user', 'What does turbidity tell me about water quality?'
FROM `aqua_ai_conversations` c
JOIN `users` u ON u.`id` = c.`user_id`
WHERE u.`email` = 'dev@aquaguard.local'
  AND c.`title` = 'Getting started with AquaGuard AI'
  AND NOT EXISTS (
    SELECT 1 FROM `aqua_ai_messages` m
    WHERE m.`conversation_id` = c.`id`
      AND m.`content` = 'What does turbidity tell me about water quality?'
  );

INSERT INTO `aqua_ai_messages` (`conversation_id`, `role`, `content`)
SELECT c.`id`, 'assistant',
  'Turbidity measures how cloudy the water is, in NTU. High turbidity means suspended particles — silt, algae or organic matter — that can shelter pathogens and reduce disinfection efficiency. Lower values are generally better for drinking water.'
FROM `aqua_ai_conversations` c
JOIN `users` u ON u.`id` = c.`user_id`
WHERE u.`email` = 'dev@aquaguard.local'
  AND c.`title` = 'Getting started with AquaGuard AI'
  AND NOT EXISTS (
    SELECT 1 FROM `aqua_ai_messages` m
    WHERE m.`conversation_id` = c.`id`
      AND m.`role` = 'assistant'
  );

-- ---------------------------------------------------------------------------
-- Confirm what was created
-- ---------------------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM `users`)                  AS seeded_users,
  (SELECT COUNT(*) FROM `water_predictions`)      AS predictions,
  (SELECT COUNT(*) FROM `alerts`)                 AS alerts,
  (SELECT COUNT(*) FROM `aqua_ai_conversations`)  AS conversations,
  (SELECT COUNT(*) FROM `aqua_ai_messages`)       AS messages;
