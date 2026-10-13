-- ===========================================================================
-- AquaGuard AI -- MySQL schema
-- ===========================================================================
-- Database : aquaguard_db
-- Engine   : InnoDB (transactions + foreign keys)
-- Charset  : utf8mb4 / utf8mb4_unicode_ci
--
-- Apply:
--   mysql -u root -p < database/schema.sql
--
-- Safe to re-run: every statement is idempotent (IF NOT EXISTS / IF EXISTS).
--
-- Design notes
--   * Passwords are stored ONLY as bcrypt digests (60 chars). No column in this
--     schema is capable of holding a plain-text password.
--   * Every child row cascades on user deletion, so removing an account cannot
--     leave orphaned predictions, alerts or conversations behind.
--   * CHECK constraints enforce the allowed vocabulary of categorical columns
--     in the database itself, not merely in application code.
--   * Measurements use DECIMAL (exact, comparable) rather than FLOAT, so a
--     stored reading always renders identically.
-- ===========================================================================

CREATE DATABASE IF NOT EXISTS `aquaguard_db`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- Application credentials.
--
-- The application connects as `aquaguard_ai`, which holds privileges on
-- `aquaguard_db` only. Flask should never connect as `root`: a compromised
-- application would then hold the whole server rather than its own schema.
--
-- This file does NOT create users or grants: schema.sql should be runnable by
-- an account that owns its database but cannot administer the server. If you
-- need to provision the user, use database/create_app_user.sql.
-- ---------------------------------------------------------------------------

USE `aquaguard_db`;


-- ===========================================================================
-- 1. users
-- ===========================================================================
CREATE TABLE IF NOT EXISTS `users` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `name`          VARCHAR(120)    NOT NULL                COMMENT 'Display name',
  `email`         VARCHAR(190)    NOT NULL                COMMENT 'Login identifier, unique',
  -- bcrypt is always 60 chars; 255 leaves room for a future algorithm change.
  `password_hash` VARCHAR(255)    NOT NULL                COMMENT 'bcrypt digest -- never plain text',
  `role`          VARCHAR(20)     NOT NULL DEFAULT 'user' COMMENT 'user | admin',
  -- Self-service password reset. One pending code per account: hashed here,
  -- with its expiry (epoch seconds) and a failure count. A new request replaces
  -- the previous code, so a stale code can never be replayed.
  `reset_code_hash`        VARCHAR(255) NULL COMMENT 'bcrypt hash of the pending reset code',
  `reset_code_expires_at`  INT          NULL COMMENT 'Epoch seconds the code stops working',
  `reset_code_attempts`    INT          NOT NULL DEFAULT 0 COMMENT 'Wrong guesses so far',
  `created_at`    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  -- 190 chars is the largest VARCHAR that fits a utf8mb4 unique index inside
  -- InnoDB's 3072-byte key limit (190 * 4 = 760 bytes, safely under it).
  UNIQUE KEY `uq_users_email` (`email`),
  KEY `ix_users_created_at` (`created_at`),

  CONSTRAINT `ck_users_role`
    CHECK (`role` IN ('user', 'admin')),
  CONSTRAINT `ck_users_email_format`
    CHECK (`email` LIKE '%_@_%._%')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Registered accounts. Passwords hashed with bcrypt.';


-- ===========================================================================
-- 2. water_predictions
-- ===========================================================================
-- One row per prediction request: the six measured parameters plus the model
-- verdict and confidence. Keeping inputs and output on one row makes every
-- prediction independently reproducible and auditable.
CREATE TABLE IF NOT EXISTS `water_predictions` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `user_id`          BIGINT UNSIGNED NOT NULL                COMMENT 'Owner of this prediction',

  -- --- Measured parameters -------------------------------------------------
  `ph`               DECIMAL(4,2)    NOT NULL COMMENT 'pH, 0.00 to 14.00',
  `turbidity`        DECIMAL(8,2)    NOT NULL COMMENT 'Turbidity in NTU',
  -- TDS spans very wide real-world ranges (fresh water through brine), so it
  -- carries more integer digits than the other measurements.
  `tds`              DECIMAL(12,2)   NOT NULL COMMENT 'Total dissolved solids in mg/L',
  `temperature`      DECIMAL(5,2)    NOT NULL COMMENT 'Water temperature in Celsius',
  `dissolved_oxygen` DECIMAL(6,2)    NOT NULL COMMENT 'Dissolved oxygen in mg/L',

  -- --- Model output --------------------------------------------------------
  `prediction`       VARCHAR(20)     NOT NULL COMMENT 'safe | unsafe | moderate',
  `confidence`       DECIMAL(5,4)    NOT NULL COMMENT 'Model confidence 0.0000 to 1.0000',

  -- --- Where the sample came from ------------------------------------------
  -- Optional: predictions may still be made without a location. The COLLECTION of
  -- columns below MUST match `WaterPrediction` in app/models/water_prediction.py
  -- name for name — the ORM writes these columns directly, so a mismatch is an
  -- "Unknown column" failure on insert, not a cosmetic difference.
  `location_name`    VARCHAR(190)    NULL COMMENT 'Human-readable place name of the sample site',
  `location_city`    VARCHAR(120)    NULL COMMENT 'City / town of the sample site',
  -- Area/locality within the city, and the district, as the History/PDF field
  -- list names them. These MUST be present: the ORM writes them by name, so a
  -- database created before this line would fail every location-carrying insert
  -- with "Unknown column 'location_district'". See repair_missing_columns.py.
  `location_area`    VARCHAR(120)    NULL COMMENT 'Area / locality within the city',
  `location_district` VARCHAR(120)   NULL COMMENT 'District the sample site falls in',
  `location_state`   VARCHAR(120)    NULL COMMENT 'State/region the sample site falls in',
  `location_country` VARCHAR(120)    NULL COMMENT 'Country of the sample site',
  `location_pincode` VARCHAR(20)     NULL COMMENT 'Postal code of the sample site, when known',
  `location_lat`     DECIMAL(9,6)    NULL COMMENT 'Sample site latitude',
  `location_lng`     DECIMAL(9,6)    NULL COMMENT 'Sample site longitude',
  `water_source_type` VARCHAR(60)    NULL COMMENT 'Dominant source: river | lake | pond | well | piped | rain | tank | municipal | other',
  `nearby_water_source` VARCHAR(190) NULL COMMENT 'Nearest known water body to the sample site',
  `nearby_water_source_distance` DECIMAL(8,2) NULL COMMENT 'Distance to that water body in km',
  `param_provenance` VARCHAR(40) NULL COMMENT 'PROMPT 1 E.9: provenance of the five readings (measured | nearby_source | historical | dataset_based | estimated | user_input_required | user)',

  `created_at`       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  -- Composite index matching the History screen's real query:
  -- "this user's predictions, newest first".
  KEY `ix_water_predictions_user_created` (`user_id`, `created_at` DESC),
  -- Supports filtering history and raising alerts by verdict.
  KEY `ix_water_predictions_prediction` (`prediction`),
  -- The admin console and the location insight screens group by place.
  KEY `ix_water_predictions_location_state` (`location_state`),

  CONSTRAINT `fk_water_predictions_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,

  -- Domain guards: a reading outside physical possibility is refused by the
  -- database itself, not only by the Flask validator.
  CONSTRAINT `ck_water_predictions_ph`
    CHECK (`ph` >= 0.00 AND `ph` <= 14.00),
  CONSTRAINT `ck_water_predictions_turbidity`
    CHECK (`turbidity` >= 0.00),
  CONSTRAINT `ck_water_predictions_tds`
    CHECK (`tds` >= 0.00),
  CONSTRAINT `ck_water_predictions_temperature`
    CHECK (`temperature` >= -5.00 AND `temperature` <= 100.00),
  CONSTRAINT `ck_water_predictions_dissolved_oxygen`
    CHECK (`dissolved_oxygen` >= 0.00),
  CONSTRAINT `ck_water_predictions_confidence`
    CHECK (`confidence` >= 0.0000 AND `confidence` <= 1.0000),
  CONSTRAINT `ck_water_predictions_label`
    CHECK (`prediction` IN ('safe', 'unsafe', 'moderate'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Water quality readings and the model verdict for each.';


-- ===========================================================================
-- 3. alerts
-- ===========================================================================
-- Raised automatically when a prediction comes back unsafe. `prediction_id` is
-- nullable so system or administrative notices can exist without being tied to
-- a specific reading.
CREATE TABLE IF NOT EXISTS `alerts` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `user_id`       BIGINT UNSIGNED NOT NULL                COMMENT 'Recipient of the alert',
  `prediction_id` BIGINT UNSIGNED NULL                    COMMENT 'Source prediction, NULL for system alerts',
  `type`          VARCHAR(40)     NOT NULL DEFAULT 'water_unsafe' COMMENT 'water_unsafe | threshold_exceeded | system',
  `message`       TEXT            NOT NULL                COMMENT 'Human-readable explanation',
  `is_read`       TINYINT(1)      NOT NULL DEFAULT 0      COMMENT 'Unread badge flag',
  -- When the user dealt with this alert, or NULL while it still stands.
  --
  -- A real column, not a flag derived from `is_read`. "Seen" and "dealt with"
  -- are different states, and the bell badge counts only what is still open, so
  -- it has to be able to exclude resolved rows. Keeping the timestamp (rather
  -- than a BOOLEAN) also preserves when the resolution happened.
  `resolved_at`   TIMESTAMP       NULL     DEFAULT NULL   COMMENT 'NULL while open; set when resolved',
  `created_at`    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  -- The notification bell asks exactly one question: "how many unread alerts
  -- does this user have?" This composite index answers it without a scan.
  KEY `ix_alerts_user_is_read` (`user_id`, `is_read`),
  -- The open-alert count and the resolved filter both add `resolved_at IS NULL`
  -- to that question, so the index carries the third column too.
  KEY `ix_alerts_user_resolved` (`user_id`, `resolved_at`),
  -- One alert per prediction, enforced here rather than by convention.
  -- A plain index would allow a duplicate to be inserted silently, and the user
  -- would be paged twice for the same reading. MySQL excludes NULLs from a
  -- unique index, so alerts not tied to a prediction are unaffected.
  UNIQUE KEY `uq_alerts_prediction_id` (`prediction_id`),
  KEY `ix_alerts_created_at` (`created_at`),

  CONSTRAINT `fk_alerts_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,

  -- SET NULL rather than CASCADE: deleting a prediction must not silently erase
  -- the record that the user was warned about it.
  CONSTRAINT `fk_alerts_prediction`
    FOREIGN KEY (`prediction_id`) REFERENCES `water_predictions` (`id`)
    ON DELETE SET NULL ON UPDATE CASCADE,

  CONSTRAINT `ck_alerts_type`
    CHECK (`type` IN ('water_unsafe', 'threshold_exceeded', 'system')),
  -- MySQL has no native BOOLEAN; TINYINT(1) is the convention, constrained here.
  CONSTRAINT `ck_alerts_is_read`
    CHECK (`is_read` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Unsafe-water notifications and system notices.';


-- ===========================================================================
-- 4. aqua_ai_conversations
-- ===========================================================================
CREATE TABLE IF NOT EXISTS `aqua_ai_conversations` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `user_id`    BIGINT UNSIGNED NOT NULL                COMMENT 'Owner of this thread',
  `title`      VARCHAR(180)    NOT NULL DEFAULT 'New conversation' COMMENT 'Sidebar label',
  `created_at` TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  -- The chat sidebar lists a user's threads, most recently active first.
  KEY `ix_aqua_ai_conversations_user_updated` (`user_id`, `updated_at` DESC),

  CONSTRAINT `fk_aqua_ai_conversations_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Aqua AI chat threads.';


-- ===========================================================================
-- 5. aqua_ai_messages
-- ===========================================================================
CREATE TABLE IF NOT EXISTS `aqua_ai_messages` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `conversation_id` BIGINT UNSIGNED NOT NULL                COMMENT 'Parent thread',
  `role`            VARCHAR(20)     NOT NULL                COMMENT 'user | assistant | system',
  `content`         TEXT            NOT NULL                COMMENT 'Message body',
  `created_at`      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  -- Messages are always fetched as one ordered thread, so the index carries the
  -- ordering key: no filesort when rendering a conversation.
  KEY `ix_aqua_ai_messages_conversation_created` (`conversation_id`, `created_at`),

  CONSTRAINT `fk_aqua_ai_messages_conversation`
    FOREIGN KEY (`conversation_id`) REFERENCES `aqua_ai_conversations` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,

  CONSTRAINT `ck_aqua_ai_messages_role`
    CHECK (`role` IN ('user', 'assistant', 'system'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Individual Aqua AI chat turns.';


-- ===========================================================================
-- 6. login_events
-- ===========================================================================
-- One row per sign-in attempt, successful or not.
--
-- Append-only and separate from `users` because `users` holds the CURRENT state
-- of an account and cannot answer "when, from where, how often" without being
-- overwritten each time. Failures are recorded too: a table of successes alone
-- could not show the brute-force pattern that is the main reason to read this.
--
-- NOTHING DERIVED FROM A CREDENTIAL IS STORED. No password, no hash, no token.
-- There is no column for any of them, which is what makes that a property of the
-- table rather than something a future change has to remember.
CREATE TABLE IF NOT EXISTS `login_events` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  -- Nullable: a failed attempt for an address with no account is still worth
  -- recording, and is exactly the enumeration attempt worth noticing.
  `user_id`        BIGINT UNSIGNED NULL                    COMMENT 'NULL if the email has no account',
  `email`          VARCHAR(190)    NOT NULL                COMMENT 'Address attempted',
  `event_type`     VARCHAR(20)     NOT NULL DEFAULT 'login' COMMENT 'login | logout | register | admin_login',
  `success`        TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '1 = succeeded',
  `ip_address`     VARCHAR(45)     NULL                    COMMENT 'Client IP (45 fits IPv6)',
  `user_agent`     VARCHAR(255)    NULL                    COMMENT 'Raw agent string',
  `device`         VARCHAR(80)     NULL                    COMMENT 'Derived OS / browser label',

  -- Where the user was, as an APPROXIMATE PLACE supplied by the client after a
  -- reverse-geocode of its position (or empty when permission was refused).
  -- Nullable by design: the lookup can fail, and the notices then say "Location
  -- unavailable" rather than inventing one. Never a coordinate.
  `location_name`  VARCHAR(190)    NULL                    COMMENT 'Approximate locality name',
  `location_city`  VARCHAR(120)    NULL                    COMMENT 'Approximate city/town',
  `location_state` VARCHAR(120)    NULL                    COMMENT 'Approximate state/region',
  `location_country` VARCHAR(120)  NULL                    COMMENT 'Approximate country',
  `location_pincode` VARCHAR(20)   NULL                    COMMENT 'Approximate postal code',

  -- The SAME ambiguous wording the API returns, never "no such user" vs
  -- "wrong password". Distinguishing them would make the admin page an
  -- account-enumeration tool.
  `failure_reason` VARCHAR(120)    NULL                    COMMENT 'Ambiguous reason, never a credential',
  `created_at`     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  -- The admin page reads newest-first, optionally filtered by user or outcome.
  KEY `ix_login_events_created` (`created_at`),
  KEY `ix_login_events_user_created` (`user_id`, `created_at`),
  KEY `ix_login_events_email` (`email`),
  KEY `ix_login_events_success` (`success`),

  -- Deleting an account removes its sign-in history with it, rather than leaving
  -- an orphaned trail pointing at a user id that no longer resolves.
  CONSTRAINT `fk_login_events_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,

  CONSTRAINT `ck_login_events_type`
    CHECK (`event_type` IN ('login', 'logout', 'register', 'admin_login'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Sign-in history. Append-only; never holds a credential.';

-- ===========================================================================
-- 7. admin_settings
-- ===========================================================================
-- A SINGLE ROW, id = 1. Two rows would be two sources of truth for the admin
-- password, which is how "why will my new password not work?" happens.
--
-- This is a table rather than configuration because two required behaviours need
-- runtime state the deployment cannot hold: the admin password must be changeable
-- from the console (a .env value is immutable at runtime), and edited
-- notification templates must apply to the NEXT notification.
CREATE TABLE IF NOT EXISTS `admin_settings` (
  `id`                     INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT 'Always 1',
  -- bcrypt hash. NULL means no password has been set through the console yet, and
  -- the boot-time environment value is used to seed it on first login.
  `password_hash`          VARCHAR(255)    NULL,
  -- JSON, keyed by notification type. JSON rather than a column per type because
  -- the set of types is expected to grow, and a schema change per new type would
  -- be a schema change per new type forever.
  `notification_templates` TEXT            NULL COMMENT 'JSON: type -> {label, subject, body}',
  `notification_settings`  TEXT            NULL COMMENT 'JSON: enabled types and thresholds',
  -- JSON of per-parameter accepted bounds. NULL means "use the built-in
  -- constants", so an untouched deployment behaves exactly as before.
  `parameter_limits`       TEXT            NULL COMMENT 'JSON: parameter -> {min, max}',
  -- The console's own login name and recovery address. Stored rather than read
  -- from the environment because the requirement is that the console can change
  -- both from inside itself, and a .env value is immutable at runtime. NULL means
  -- "use the configured default", so an existing deployment keeps working.
  `admin_username`         VARCHAR(190)    NULL COMMENT 'Console login name',
  `admin_email`            VARCHAR(190)    NULL COMMENT 'Where a reset code is mailed',
  -- PROMPT 8: where LOGIN APPROVAL REQUESTS are sent. Separate from
  -- `admin_email` on purpose: the recovery address can already reset the console
  -- password, so it is an access-approver by definition, and an approval address
  -- lets an operator point approvals at a different mailbox (a security inbox, a
  -- second administrator, a group alias) without changing where reset codes go.
  -- NULL means "same as admin_email", which is exactly the previous behaviour, so
  -- an existing deployment needs no configuration change.
  `admin_approval_email`   VARCHAR(190)    NULL COMMENT 'Where login approval requests are mailed',
  -- The single pending password-reset code. A single slot rather than a table:
  -- only one reset can be in flight, and a new request replaces the old code.
  `reset_code`             TEXT            NULL COMMENT 'JSON: {code, expires_at, attempts}',
  -- The administrator-fixed location access scope. NULL mode means no
  -- restriction, so an existing deployment keeps working until an admin sets one.
  -- Only the field the mode uses is populated; switching mode clears the other.
  `location_scope_mode`    VARCHAR(20)     NULL COMMENT 'state | country | NULL (off)',
  `location_scope_state`   VARCHAR(190)    NULL COMMENT 'Allowed state when mode=state',
  `location_scope_country` VARCHAR(190)    NULL COMMENT 'Allowed country when mode=country',
  -- PROMPT 13, requirement 4: WHEN and BY WHOM the scope was last changed.
  -- Separate from `updated_at` because that column moves for every unrelated
  -- settings save, so it cannot answer "when was the SCOPE last touched".
  `location_scope_updated_at` TIMESTAMP    NULL COMMENT 'Last SCOPE change, not the row timestamp',
  `location_scope_updated_by` VARCHAR(190) NULL COMMENT 'Console identity of the last scope change',
  `created_at`             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                           ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  -- Enforces the single-row design in the database rather than by convention, so
  -- a second row cannot be inserted by a stray INSERT.
  CONSTRAINT `ck_admin_settings_singleton`
    CHECK (`id` = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Single-row admin console state.';

-- ===========================================================================
-- 8. admin_login_approvals
-- ===========================================================================
-- ONE ROW PER ADMIN LOGIN AWAITING AN EMAILED DECISION.
--
-- The pre-existing workflow held a single pending confirmation in a JSON column,
-- which meant one sign-in attempt at a time: a second attempt overwrote the first,
-- and answering one mail decided the other. Each attempt is a row here instead, so
-- attempts are independent and each is answered on its own terms.
--
-- EVERY BINDING IN REQUIREMENT 10 IS A COLUMN, OR THE ABSENCE OF ONE:
--
--   `action_token_hash`  the MAIL's authority - single-use, short-lived, and
--                         required AGAIN at unlock time, so an approval cannot be
--                         spent later by whoever finds the request id.
--   `challenge_hash`     binds the DECISION to the BROWSER that asked. The clear
--                         value never leaves the login page, so it cannot leak
--                         through a URL, a Referer header, a proxy log or the
--                         browser history - which is exactly what a cookie or a
--                         query parameter would do.
--   `attempt_nonce`      ties a request to one attempt, so a token minted for one
--                         cannot answer another even when both are in flight.
--   `expires_at`         the short window. Evaluated on every READ as well as on
--                         every decision, so an expired request is refused the
--                         instant it is presented rather than whenever a cleanup
--                         task happens to run.
--
-- `action_token_hash` is the ONLY copy of the token on this side. The clear value
-- lives in the mail and nowhere else, which is what makes a database dump
-- worthless as an approval credential.
--
-- NOT STORED: the password, any hash of the password, any console credential, and
-- the plain action token. `credential_shape` records only WHICH FIELDS were
-- supplied, which is what an audit trail needs; their values are never recorded.
CREATE TABLE IF NOT EXISTS `admin_login_approvals` (
  `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  -- The handle the login page polls with. It identifies WHICH attempt is being
  -- watched; it is NOT the authority to decide it. Only the mail's action token
  -- is, so learning this value grants nothing.
  `request_id`         VARCHAR(64)     NOT NULL COMMENT 'Opaque handle for polling',
  -- The console username, verified by the caller before this row was created.
  `admin_username`     VARCHAR(190)    NOT NULL,

  -- SHA-256 hex of the mail's action token. Stored instead of the token.
  `action_token_hash`  CHAR(64)        NOT NULL COMMENT 'SHA-256 of the single-use action token',
  -- SHA-256 hex of the login page's browser challenge. Stored instead of the value.
  `challenge_hash`     CHAR(64)        NOT NULL COMMENT 'SHA-256 of the browser challenge',
  `attempt_nonce`      VARCHAR(64)     NOT NULL COMMENT 'Binds a token to this one attempt',

  -- --- Context the approver sees, so they can recognise their own machine -----
  -- `device_label` is derived from the user agent and identifies a BROWSER, not a
  -- person. `ip_address` is `remote_addr` only: `X-Forwarded-For` is
  -- client-controlled, and trusting it would let an attacker write whatever
  -- address they liked into the audit trail - the one place this is stored.
  `requested_at`       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `ip_address`         VARCHAR(45)     NULL     COMMENT 'remote_addr only',
  `user_agent`         VARCHAR(255)    NULL,
  `device_label`       VARCHAR(120)    NULL     COMMENT 'e.g. "Chrome on Windows"',
  -- WHICH credential fields were present. Never their values.
  `credential_shape`   VARCHAR(40)     NULL     COMMENT 'Which fields were supplied',

  `status`             VARCHAR(20)     NOT NULL DEFAULT 'pending'
    COMMENT 'pending | approved | denied | expired | consumed',
  `expires_at`         TIMESTAMP       NOT NULL,
  `decided_at`         TIMESTAMP       NULL,
  `decided_by`         VARCHAR(190)    NULL,
  `decision_detail`    VARCHAR(500)    NULL COMMENT 'Why; never a token',
  -- Set once the decision has been SPENT. This is what makes a request
  -- single-use: even if the status were somehow rewound, this would still refuse.
  `consumed_at`        TIMESTAMP       NULL,

  `created_at`         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                         ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  UNIQUE KEY `uq_admin_login_approvals_request` (`request_id`),
  KEY `ix_admin_login_approvals_status` (`status`),
  KEY `ix_admin_login_approvals_expires` (`expires_at`),
  KEY `ix_admin_login_approvals_requested` (`requested_at`),
  KEY `ix_admin_login_approvals_action_token` (`action_token_hash`),

  -- A fixed vocabulary, so a row cannot hold a status nothing knows how to read.
  CONSTRAINT `ck_admin_login_approvals_status`
    CHECK (`status` IN ('pending', 'approved', 'denied', 'expired', 'consumed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='One row per admin login awaiting an emailed approve/deny decision.';

-- ===========================================================================
-- 9. model_versions
-- ===========================================================================
-- One row per registered ML model artifact: its own version string, its checksum,
-- the feature and label schema it was built against, and where it is in the
-- lifecycle.
--
-- The ACTIVATION ITSELF IS NOT HERE. The active model is still the single
-- pointer `model_service` writes into `admin_settings`, and nothing in this
-- table can change it directly. This table records the history AROUND that
-- pointer so the console can answer "which model is deployed, what version is
-- it, and when was it last updated", and can roll back to a version that was
-- actually validated rather than to any file that happens to be on disk.
--
-- THE STATE MACHINE IS THE SAFETY PROPERTY:
--     registered -> validating -> validated | rejected
--                               validated  -> active
--     active -> superseded (replaced by a newer one)
--     active -> rolled_back (replaced by an older known-good one)
-- Nothing promotes an artifact into `active` from any state other than
-- `validated`, and the application refuses to promote one whose own recorded
-- validation did not pass. A failed validation therefore cannot disturb a
-- working model: it produces a `rejected` row and nothing else.
--
-- `artifact_path` and `filename` are SERVER-GENERATED from a conservative
-- allowlist, never taken from the upload as-is - an upload's filename is
-- attacker-controlled and must not be able to reach a path outside the import
-- directory.
CREATE TABLE IF NOT EXISTS `model_versions` (
  `id`                  INT UNSIGNED   NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  -- Unique, so the same version string cannot become two rows that both look
  -- authoritative.
  `version`             VARCHAR(120)   NOT NULL                COMMENT 'Admin-supplied version string',
  `display_name`        VARCHAR(190)   NULL,
  -- Server-generated basename and full location inside the import directory.
  `filename`            VARCHAR(255)   NOT NULL,
  `artifact_path`       VARCHAR(512)   NOT NULL,
  `size_bytes`          BIGINT UNSIGNED NULL,
  -- SHA-256 of the STORED file's bytes, computed at import, describing what is
  -- on disk rather than what the client said it sent.
  `checksum_sha256`     CHAR(64)       NULL,
  -- Recorded for the audit view only. Neither is trusted for validation: the
  -- extension and the bytes are what decide.
  `original_filename`   VARCHAR(255)   NULL,
  `content_type`        VARCHAR(120)   NULL,
  -- The schema the artifact was built against, captured at import so a later
  -- change to the configured features is detectable against an older model.
  `feature_schema`      TEXT           NULL COMMENT 'JSON: feature names',
  `label_schema`        TEXT           NULL COMMENT 'JSON: label names',
  -- What the artifact itself claims about itself, when it is an envelope with
  -- those keys.
  `declared_version`    VARCHAR(120)   NULL,
  `trained_at`          VARCHAR(64)    NULL,
  -- A model trained on a different scikit-learn major is a real compatibility
  -- risk, and the only way to know is to have kept the number.
  `scikit_learn_version` VARCHAR(40)   NULL,
  `numpy_version`       VARCHAR(40)    NULL,
  `status`              VARCHAR(24)    NOT NULL DEFAULT 'registered'
    COMMENT 'registered | validating | validated | rejected | active | superseded | rolled_back',
  -- JSON. `passed` is the flag `activate` gates on, and it is set only from the
  -- isolated validation subprocess's own verdict.
  `validation_report`   TEXT           NULL COMMENT 'JSON: {passed, checks[], failure, ...}',
  `validated_at`        TIMESTAMP      NULL,
  -- The console identity. Never an IP, a token or a credential.
  `validated_by`        VARCHAR(190)   NULL,
  `registered_by`       VARCHAR(190)   NULL,
  `activated_at`        TIMESTAMP      NULL,
  `activated_by`        VARCHAR(190)   NULL,
  `notes`               VARCHAR(500)   NULL,
  `created_at`          TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`          TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                         ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_model_versions_version` (`version`),
  KEY `ix_model_versions_status` (`status`),
  KEY `ix_model_versions_checksum` (`checksum_sha256`),

  -- THE ONLY WAY INTO `active`. This is the requirement "preserve the active
  -- model if validation or deployment fails" enforced by the database itself:
  -- an artifact that failed validation, or was never validated, cannot be marked
  -- active by any code path - including a future one nobody has reviewed yet.
  CONSTRAINT `ck_model_versions_activation`
    CHECK (`status` <> 'active' OR (`validated_at` IS NOT NULL AND `validated_by` IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Registered ML model artifacts and their validation state.';

-- ===========================================================================
-- 10. model_audit_logs
-- ===========================================================================
-- One row per ATTEMPTED change to the model registry - including the failures.
--
-- "Someone tried to activate a model that failed validation" is exactly the
-- event nobody wants to discover from the behaviour of a running system instead,
-- so a table of successes alone would not answer the question this exists to
-- answer. There is no UPDATE or DELETE path on this table anywhere in the
-- application.
--
-- `model_version` is a plain string rather than a foreign key, so a log line
-- survives the row it refers to being deleted: the record of the deletion is the
-- row you most want to keep.
--
-- NO SECRET IS STORED HERE. `detail` is a short human explanation, never a
-- credential, an API key, or a traceback that might contain one.
CREATE TABLE IF NOT EXISTS `model_audit_logs` (
  `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  -- The console identity that acted - the same value the rest of the console
  -- audits with.
  `actor`             VARCHAR(190)   NOT NULL COMMENT 'Console identity',
  `model_version`     VARCHAR(120)   NULL,
  `action`            VARCHAR(32)    NOT NULL
    COMMENT 'register | validate | activate | rollback | supersede | reject | delete',
  `success`           TINYINT(1)     NOT NULL DEFAULT 0 COMMENT '0 = failed or refused',
  `detail`            VARCHAR(500)   NULL COMMENT 'Short reason; never a credential',
  -- What was active before and after, so a rollback is legible from the log
  -- alone without reconstructing it from version ordering.
  `previous_active`   VARCHAR(120)   NULL,
  `resulting_active`  VARCHAR(120)   NULL,
  `occurred_at`       TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),

  -- Newest-first is the only order the console reads this in.
  KEY `ix_model_audit_occurred` (`occurred_at`),
  KEY `ix_model_audit_actor` (`actor`),
  KEY `ix_model_audit_version` (`model_version`),
  KEY `ix_model_audit_action` (`action`),
  KEY `ix_model_audit_success` (`success`),

  -- A fixed vocabulary, so the log cannot accumulate entries nothing knows how to
  -- read. Matches `app.models.model_version.ACTIONS`.
  CONSTRAINT `ck_model_audit_action`
    CHECK (`action` IN ('register', 'validate', 'activate', 'rollback',
                        'supersede', 'reject', 'delete'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only trail of every ML model registry change.';

-- ===========================================================================
-- 11. report_email_audits (PROMPT 12)
-- ===========================================================================
-- One append-only row per Reports-to-Mail request — the audit trail of who
-- asked for a report by email, when, and what the transport actually did.
--
-- NO SECRET AND NO REPORT CONTENT IS STORED HERE. There is no column for a
-- password, a token, or the attachment's contents, so no future change can
-- forget and start writing one.
--
-- LOCATION IS OPTIONAL AND EXPLICIT. The location_* columns are filled ONLY
-- when the requester's browser granted geolocation and the resulting fix was
-- reverse-geocoded (location_source = 'browser', the only accepted value),
-- and only at PLACE granularity — never coordinates, never an inference.
-- Rows without a consented location carry NULLs and the admin view reads
-- them as "Location unavailable" rather than inventing one.
CREATE TABLE IF NOT EXISTS `report_email_audits` (
  `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  -- The address the report was sent to, exactly as validated.
  `recipient_email`    VARCHAR(190)   NOT NULL,
  -- REPORT_PDF | REPORT_CSV | ALL_PDF | ALL_CSV
  `report_option`      VARCHAR(20)    NOT NULL,
  -- The transport's OWN verdict, stored verbatim:
  -- sent | failed | suppressed | disabled | unconfigured
  `delivery_status`    VARCHAR(30)    NOT NULL,
  `reports_included`   INT            NULL,
  -- The account whose reports were mailed (SET NULL on account deletion, with
  -- the display name copied below so the row stays readable).
  `user_id`            BIGINT UNSIGNED NULL,
  `requester_name`     VARCHAR(120)   NULL,
  -- The console username only when the console itself asked for the mail.
  `admin_username`     VARCHAR(120)   NULL,
  -- Consented, place-granularity location. NULL when not legitimately available.
  `location_name`      VARCHAR(190)   NULL,
  `location_city`      VARCHAR(120)   NULL,
  `location_state`     VARCHAR(120)   NULL,
  `location_country`   VARCHAR(120)   NULL,
  `location_pincode`   VARCHAR(20)    NULL,
  -- How the place was obtained; only 'browser' is accepted by the writer.
  `location_source`    VARCHAR(20)    NULL,
  -- Short platform/browser label; never a fingerprint.
  `device_label`       VARCHAR(80)    NULL,
  `created_at`         TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        COMMENT 'Request timestamp (UTC)',

  PRIMARY KEY (`id`),
  KEY `ix_report_email_recipient` (`recipient_email`),
  KEY `ix_report_email_option` (`report_option`),
  KEY `ix_report_email_status` (`delivery_status`),
  KEY `ix_report_email_user` (`user_id`),
  KEY `ix_report_email_created` (`created_at`),
  CONSTRAINT `fk_report_email_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only trail of report-download-by-email requests.';

-- ===========================================================================
-- 12. location_scope_audits (PROMPT 13)
-- ===========================================================================
-- One row per ATTEMPTED change to the administrative location scope.
--
-- This setting decides WHO MAY USE the water-quality feature at all, so "who
-- changed it, when, and from what to what" is the question an administrator
-- most needs answered afterwards. The current setting cannot answer it: it
-- records only what is true NOW, and a mistake is corrected by overwriting.
--
-- FAILED ATTEMPTS ARE RECORDED, which is the point of a log rather than a
-- counter: "someone tried to open the scope to a country that does not exist"
-- is exactly the event nobody wants discovered from the behaviour of a running
-- system instead. There is NO UPDATE or DELETE path on this table anywhere in
-- the application.
--
-- NO SECRET IS STORED. `detail` is a short human sentence; it is never
-- populated with a credential, an API key or a traceback that might contain one.
--
-- CHANGING SCOPE DELETES NOTHING. Predictions, reports and other history that
-- predate a narrowing remain stored; only their READ visibility is restricted.
CREATE TABLE IF NOT EXISTS `location_scope_audits` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  -- The console identity that made the change. Never a user account or token.
  `actor`           VARCHAR(190)   NOT NULL COMMENT 'Console identity',
  -- What the admin was trying to SET (all NULL means: clear the scope).
  `new_mode`        VARCHAR(20)    NULL COMMENT 'state | country | NULL=off',
  `new_state`       VARCHAR(190)   NULL,
  `new_country`     VARCHAR(190)   NULL,
  -- What was in force BEFORE, so the change is legible from the log alone.
  -- All NULL means the scope was off before this change.
  `previous_mode`   VARCHAR(20)    NULL,
  `previous_state`  VARCHAR(190)   NULL,
  `previous_country` VARCHAR(190)  NULL,
  -- 0 when the change was REFUSED (an unresolvable state, a missing country).
  `success`         TINYINT(1)     NOT NULL DEFAULT 0 COMMENT '0 = refused',
  -- Short human explanation; never a credential, never a raw traceback.
  `detail`          VARCHAR(500)   NULL,
  `occurred_at`     TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  KEY `ix_scope_audit_actor` (`actor`),
  KEY `ix_scope_audit_new_mode` (`new_mode`),
  KEY `ix_scope_audit_success` (`success`),
  KEY `ix_scope_audit_occurred` (`occurred_at`),

  CONSTRAINT `ck_scope_audit_mode`
    CHECK (`new_mode` IS NULL OR `new_mode` IN ('state', 'country'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only trail of admin location-scope changes.';

-- ===========================================================================
-- Reporting view
-- ===========================================================================
-- Convenience read model joining predictions to their owner and any alerts.
-- Backs the dashboard and history screens without duplicating stored rows.
CREATE OR REPLACE VIEW `vw_user_predictions` AS
SELECT
  p.`id`               AS prediction_id,
  p.`user_id`          AS user_id,
  u.`name`             AS user_name,
  u.`email`            AS user_email,
  p.`ph`               AS ph,
  p.`turbidity`        AS turbidity,
  p.`tds`              AS tds,
  p.`temperature`      AS temperature,
  p.`dissolved_oxygen` AS dissolved_oxygen,
  p.`prediction`       AS prediction,
  p.`confidence`       AS confidence,
  p.`created_at`       AS created_at,
  COUNT(a.`id`)        AS alert_count,
  SUM(CASE WHEN a.`is_read` = 0 THEN 1 ELSE 0 END) AS unread_alert_count
FROM `water_predictions` p
JOIN `users` u ON u.`id` = p.`user_id`
LEFT JOIN `alerts` a ON a.`prediction_id` = p.`id`
GROUP BY p.`id`;
