# AquaGuard AI — Database Design
**MySQL 8.0 · Database `aquaguard_db` · InnoDB · utf8mb4_unicode_ci**

DDL lives in `backend/database/schema.sql`. Apply it with:

```powershell
mysql -u root -p < backend/database/schema.sql
```

The file is **idempotent** — `IF NOT EXISTS` and `CREATE OR REPLACE VIEW` mean re-running it is
a no-op, not an error. It creates no users and no grants, so it stays runnable by an account
that owns its database but cannot administer the server.

---

## Entity relationships
```
users ─┬─< water_predictions   (1:N, CASCADE)
       │        └─< alerts      (1:N, SET NULL on prediction delete)
       ├─< alerts               (1:N, CASCADE)
       └─< aqua_ai_conversations (1:N, CASCADE)
                └─< aqua_ai_messages (1:N, CASCADE)

vw_user_predictions   — read-only view joining predictions + owner + alert counts
```

Deleting a user removes all 4 dependent row types. **Verified by test**, not assumed.

<!-- LEGACY ER DIAGRAM (previous 8-table design) retained for history:
users ─┬─< refresh_tokens      (1:N, cascade delete)
       │                 ├─< prediction_history (1:1 projection)
       │                 └─< alerts             (1:N, nullable)
       ├─< alerts              (1:N, cascade delete)
       └─< ai_conversations    (1:N, cascade delete)
                └─< ai_messages (1:N, cascade delete)
```

## Tables

### `users`
Account identity and profile. `email` is unique. `password_hash` stores a bcrypt digest
(60 chars) — plaintext is never persisted. `role` is `user` or `admin`.

### `refresh_tokens`
Persisted so sessions can actually be revoked. Stores a **SHA-256 digest** in `token_hash`
(never the token itself) plus `jti`, `expires_at` and a `revoked` flag. `ON DELETE CASCADE`
from `users` means deleting an account invalidates every session immediately.

### `water_samples`
Raw user-submitted parameters, one row per sample. The nine model features are `DECIMAL`
columns (continuous physical measurements, and new parameters can be added without rewriting
the table). Kept separate from `predictions` so retraining can re-score existing samples
without re-entry.

### `predictions`
The authoritative ML output. Stores both the class (`predicted_class`, `label`) and the
probabilities, so confidence is never recomputed from a single number. `input_features` holds
a JSON snapshot of the nine values, and `feature_contributions` holds per-parameter influence
for the history detail view. `model_name` / `model_version` record which artifact produced the
row.

A `CHECK (predicted_class IN (0, 1))` constraint enforces the binary domain at the database
level, not only in Python.

### `prediction_history`
A denormalised **projection** of `predictions` for the read-heavy History screen. Carries
`label`, `confidence`, `risk_level` and a compact `feature_summary`, with `predicted_on` as a
`DATE` for range filtering. Written in the same transaction as the prediction, so it cannot
diverge from the authoritative row. Uniqueness on `prediction_id` enforces the 1:1 nature.

### `alerts`
Raised when a prediction flags unsafe water. `alert_type`, `severity`, `status` are
constrained by `CHECK` clauses. `triggered_by` holds a JSON list of the parameters that
breached their range. Lifecycle timestamps (`acknowledged_at`, `resolved_at`) make the alert
auditable rather than transient UI state.

### `ai_conversations` / `ai_messages`
Chat threads and their turns. `context_summary` holds a rolling summary of older turns so a
long conversation stays inside the LLM context window without losing the thread.
`ai_messages` records `tool_name`, `tool_payload` and `tool_result`, so every action Aqua AI
took on the user's behalf is auditable and replayable. `tokens_used` and `latency_ms` give
cost visibility.

## Indexing rationale

The indexes are chosen against the actual read paths, not applied uniformly:

| Index | Query it serves |
| --- | --- |
| `predictions (user_id, created_at DESC)` | Dashboard + history: "this user's predictions, newest first" |
| `prediction_history (user_id, predicted_on DESC)` | History with a date-range filter |
| `alerts (user_id, status)` | The notification badge: "this user's active alerts" |
| `refresh_tokens (token_hash)` unique | Token validation on every refresh |
| `users (email)` unique | Login lookup, and enforcing one account per email |

`ON DELETE CASCADE` throughout means deleting a user is a single statement and leaves no
orphaned rows — `prediction_history` and `alerts` both reference `predictions`, and both are
removed transitively.

## Charset

Every table is `utf8mb4` / `utf8mb4_unicode_ci`. Note that `μS/cm` (conductivity) and
`μg/L` (trihalomethanes) are non-ASCII — a `utf8` (3-byte) or `latin1` column would corrupt
them.

## Provisioning

```powershell
mysql -u root -p < backend/database/schema.sql
```

This creates both `aquaguard` and `aquaguard_test` — the test database is separate so pytest
can never mutate development data.

Alternatively, let SQLAlchemy build it from the models:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -c "from app import create_app; from app.extensions import db; app = create_app(); app.app_context().push(); db.create_all()"
```

For schema changes beyond the initial setup, use Flask-Migrate (already installed):

```powershell
flask db init      # once
flask db migrate -m "describe the change"
flask db upgrade
```
---

## Tables

### 1. `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGINT UNSIGNED` PK | Auto-increment |
| `name` | `VARCHAR(120)` | Display name |
| `email` | `VARCHAR(190)` | `UNIQUE` — login identifier |
| `password_hash` | `VARCHAR(255)` | **bcrypt digest only**, never plain text |
| `role` | `VARCHAR(20)` | `user` \| `admin`, `CHECK` constrained |
| `created_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` |
| `updated_at` | `TIMESTAMP` | Auto-updates `ON UPDATE` |

`VARCHAR(190)` for email is not arbitrary: it is the largest length that fits a utf8mb4 unique
index within InnoDB's 3072-byte key limit (190 × 4 = 760 bytes). A longer unique column fails
at creation time.

### 2. `water_predictions`

Six measured parameters plus the model verdict, on one row — so every prediction is
independently reproducible and auditable.

| Column | Type | Constraint |
| --- | --- | --- |
| `ph` | `DECIMAL(4,2)` | `0.00 – 14.00` |
| `turbidity` | `DECIMAL(8,2)` | `>= 0` |
| `tds` | `DECIMAL(12,2)` | `>= 0` — wider range (fresh water → brine) |
| `temperature` | `DECIMAL(5,2)` | `-5.00 – 100.00` °C |
| `dissolved_oxygen` | `DECIMAL(6,2)` | `>= 0` |
| `prediction` | `VARCHAR(20)` | `safe` \| `unsafe` \| `moderate` |
| `confidence` | `DECIMAL(5,4)` | `0.0000 – 1.0000` |

`DECIMAL` rather than `FLOAT`: exact and comparable, so a stored reading always renders
identically and `SUM`/`AVG` do not drift.

**Location columns.** A prediction made from the Location flow also stores `location_name`,
`location_city`, `location_state`, `location_country`, `location_pincode`, `location_lat`,
`location_lng`, `water_source_type`, `nearby_water_source` and `nearby_water_source_distance`. All are
nullable, so a prediction without a location stays valid. **These names must match
`WaterPrediction` exactly** — the ORM writes them directly, so a mismatch (`location_label` vs
`location_name`, or a missing `location_city`) fails the insert with *“Unknown column”* and the
location never reaches the history. `database/add_water_prediction_location_columns.py` is the
idempotent step that brings an older table in line (it renames `location_label` and adds whatever is
missing); `schema.sql` already carries the correct columns for a fresh database.

### 3. `alerts`

| Column | Type | Notes |
| --- | --- | --- |
| `prediction_id` | `BIGINT UNSIGNED NULL` | Nullable — system notices have no source prediction |
| `type` | `VARCHAR(40)` | `water_unsafe` \| `threshold_exceeded` \| `system` |
| `is_read` | `TINYINT(1)` | MySQL has no `BOOLEAN`; constrained to `0,1` |

**`prediction_id` is `ON DELETE SET NULL`, not `CASCADE`.** Deleting a prediction must not
silently erase the record that the user was warned about it — the alert is evidence.

### 4. `aqua_ai_conversations`

Thread metadata. `title` defaults to `'New conversation'`. `updated_at` doubles as the
"last activity" sort key for the sidebar.

### 5. `aqua_ai_messages`

One row per turn. `role` is `CHECK` constrained to `user` \| `assistant` \| `system`.

---

## Indexing rationale

Indexes are chosen against real query paths, not applied uniformly.

| Index | Query it serves |
| --- | --- |
| `users (email)` UNIQUE | Login lookup + enforcing one account per email |
| `water_predictions (user_id, created_at DESC)` | History: "this user's predictions, newest first" |
| `water_predictions (prediction)` | Filtering history by verdict |
| `alerts (user_id, is_read)` | Notification bell: "how many unread alerts for this user?" |
| `alerts (prediction_id)` | FK join from prediction → alerts |
| `aqua_ai_conversations (user_id, updated_at DESC)` | Chat sidebar, most recently active first |
| `aqua_ai_messages (conversation_id, created_at)` | Rendering one thread — carries the ordering key, so no filesort |

---

## Verification

Everything below was executed against the live database, not assumed.

### Structure — 5 tables, all InnoDB

```
users                    InnoDB
water_predictions        InnoDB
alerts                   InnoDB
aqua_ai_conversations    InnoDB
aqua_ai_messages         InnoDB
vw_user_predictions      (view)
```

### Constraints — 5 foreign keys

| Table | FK | References | On delete |
| --- | --- | --- | --- |
| `water_predictions` | `fk_water_predictions_user` | `users(id)` | CASCADE |
| `alerts` | `fk_alerts_user` | `users(id)` | CASCADE |
| `alerts` | `fk_alerts_prediction` | `water_predictions(id)` | SET NULL |
| `aqua_ai_conversations` | `fk_aqua_ai_conversations_user` | `users(id)` | CASCADE |
| `aqua_ai_messages` | `fk_aqua_ai_messages_conversation` | `aqua_ai_conversations(id)` | CASCADE |

12 `CHECK` constraints enforce role, alert type/severity, message role, the prediction label
and the physical range of all six measurements.

### Constraint tests — all 5 correctly rejected

| Attempt | Result |
| --- | --- |
| `ph = 99.00` | rejected (above 14.00) |
| `prediction = 'banana'` | rejected (not in allowed set) |
| `role = 'superuser'` | rejected |
| duplicate `email` | rejected (unique index) |
| `user_id = 99999` (nonexistent) | rejected (FK) |

### Cascade test

Inserted a user with 1 prediction, 1 alert, 1 conversation, 1 message → deleted the user → all
4 dependent rows gone, zero orphans. Run inside a transaction and rolled back, so nothing
persisted.

### Flask connection

```
python -m app.db_check
  [PASS] Connected to MySQL 8.0.43
  [PASS] Using schema `aquaguard_db`
  [PASS] All 5 tables present
  [PASS] 5 foreign key constraints enforced
  [PASS] Every table uses InnoDB
  [PASS] INSERT permission verified (rolled back, nothing stored)
```

Over live HTTP: `GET /api/v1/health/database` → `{"database": "aquaguard_db", "status": "connected"}`

---

## Seed data

`seed_dev.sql` is **optional and never applied automatically**:

```powershell
mysql -u root -p aquaguard_db < backend/database/seed_dev.sql          # apply
mysql -u root -p aquaguard_db < backend/database/seed_dev_cleanup.sql  # undo
```

Seeds **one** dev account (`dev@aquaguard.local` / `DevPassword123`, bcrypt cost 12) and
**one** Aqua AI conversation.

It deliberately seeds **zero rows into `water_predictions` and `alerts`**. Prediction history
is the primary thing this project demonstrates; seeding it would fill the dashboard and charts
with numbers the model never produced. Both tables start genuinely empty, and the first real
prediction creates the first real row.

Current state after seeding: `1 user, 0 predictions, 0 alerts, 1 conversation, 2 messages`.

---

## Application credentials

`.env` connects as `aquaguard_ai`, which holds **only** `SELECT, INSERT, UPDATE, DELETE` on
`aquaguard_db` — no DDL, no other schema, no `GRANT`, no `FILE`.

Flask connecting as `root` would mean a single SQL injection or leaked `.env` hands over the
entire MySQL server. To provision the account as an administrator, use
`database/create_app_user.sql`.

## A note on the connection URI

`config.py` percent-encodes every URI component. This is not cosmetic: a password containing
`@` (a common choice, e.g. `user@2024`) has that `@` parsed as the user/host separator. The
result is a confusing `getaddrinfo failed` for a nonsensical hostname rather than an
authentication error, which sends you looking in entirely the wrong place.

`quote_plus` handles `@ : / # ? &` and the rest, for the user, password and database name
independently. This was the first real bug found while wiring the database up.
