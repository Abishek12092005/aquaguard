# AquaGuard AI — Project Workflow

## End-to-end flow

```
  User Login
      ↓
  Dashboard
      ↓
  Enter Water Quality Parameters
      ↓
  React Frontend  ──axios / JSON──▶  Flask REST API
                                          ↓
                                    Input Validation
                                          ↓
                                    Preprocessing
                                          ↓
                                Random Forest ML Model
                                          ↓
                                Prediction + Confidence
                                          ↓
                                      MySQL Storage
                                          ↓
                          Dashboard / Prediction History
                                          ↓
                                    Unsafe Alert
```

## What each step actually does

**User Login.** `POST /auth/login` verifies a bcrypt hash and returns a short-lived access
token plus a revocable refresh token. The React `AuthContext` stores them and the Axios
interceptor attaches the bearer token to every later call. There is no demo bypass.

**Enter Water Quality Parameters.** The nine-input form on `/predict` is *generated* from
`GET /dashboard/parameters`, so its fields, units and bounds are the backend's own contract —
the form cannot drift from the validator or the model.

**Input Validation.** `validate_water_quality_payload()` coerces every value to `float`,
checks it against `FEATURE_BOUNDS`, and returns a `422` listing **all** offending fields at
once rather than failing on the first.

**Preprocessing.** `preprocess_input()` builds a 1×9 DataFrame in the canonical order taken
from `FEATURE_NAMES` — never from the caller's dict order. The training script imports this
same function, so train/serve parity is structural, not a convention.

**Random Forest.** The artifact is loaded once per process and cached. `predict_proba()`
returns both class probabilities; the class is taken from the potability probability and the
confidence is the probability of the predicted class.

**Prediction + Confidence.** `resolve_risk_level()` maps class and confidence onto
`safe` / `moderate` / `unsafe`. An unsafe verdict is never below `moderate`, and a potable
verdict is only fully `safe` when the model is confident — borderline results stay visible
instead of turning green.

**MySQL Storage.** Four writes in one transaction: `water_samples`, `predictions`,
`prediction_history` (the read-optimised projection) and, when unsafe, `alerts`.

**Dashboard / History.** Reads back from the database. `prediction_history` and the
`(user_id, created_at DESC)` index the dashboard and history list.

**Unsafe Alert.** An unsafe prediction raises an `alerts` row, shown as a badge in the navbar
and sidebar and managed on `/alerts`.

## Aqua AI alongside the flow

Aqua AI is not a separate pipeline — it reaches the same services.

| User says | Tool requested | Executed by |
| --- | --- | --- |
| "Open my alerts" | `navigate_to_page { route: "/alerts" }` | Client — React Router |
| "How many unsafe samples this month?" | `get_prediction_summary` | Server — `prediction_service` |
| "What does turbidity mean?" | `explain_parameter` | Server — static metadata |
| "Check pH 6.5, hardness 180, …" | `run_prediction` | Server — `prediction_service.run_prediction()` |

The model may only name a tool from the catalogue in `utils/ai_tools.py`. Anything else is
rejected with `403` before it can act — the assistant cannot widen its own capabilities.

## The location flow, alongside the prediction flow

The Location page is the second way into the same Random Forest. It identifies **where** the water
is before asking the user for its readings:

```
  User searches a place / uses device location / picks on the map
      ↓
  GET /locations/resolve  or  /locations/reverse      (place -> a named, verified place)
      ↓
  Admin scope check                                   (403 when outside the configured area)
      ↓
  GET /locations/context
      ├─ water         the source type + nearby sources with real distances  (OSM)
      ├─ rain          rain status (none / occurring / expected soon) + alert
      ├─ risks         the named risks this source carries
      ├─ risk_level    the low / moderate / high category, and why
      └─ default_parameters
      ↓
  "Go to Predict"  ── router state: readings + place + provenance ──▶  POST /predictions/predict
```

On the Predict page the readings are **labelled by where they came from** — `Estimated`,
`Dataset-based` or `User input required` — never shown as a measurement. The five inputs stay
editable, an edited value becomes the user's own reading, and the form still submits through the
single `POST /predictions/predict` path.

### Step 8 — the prediction itself

On **Analyze Water Quality**, the page sends the five readings **and** the identified location to
`POST /predictions/predict`. The Random Forest reads only the five parameters; the location is
stored as a label and echoed back. The result panel shows the place, the water source, the verdict,
the model's own confidence, a risk word mapped from that verdict (safe → Low, moderate → Medium,
unsafe → High) and the parameters. Nothing is synthesised: an unavailable model is a `503`, not a
made-up verdict, and the panel ends with *“AI-based prediction. This result is not a substitute for
certified laboratory water testing.”*

### Step 9 — the location travels with the record

Because the location rides on the prediction and is stored on the row, it appears everywhere a record
is read, with no second lookup:

| Surface | Shows |
| --- | --- |
| **Prediction History** | 📍 place and 💧 water source per row, plus the full block in the detail panel |
| **Reports** | Location and Water Source in the report sheet, the CSV export and the PDF |
| **Admin console** | a Location column (place + source) on the report table and in its CSV export |

**PRIVACY.** A privileged reader sees the location as a PLACE (name, city, state, country, pincode,
water source) so results can be grouped and followed up — never the exact `location_lat` /
`location_lng`. `WaterPrediction.place_dict()` is the boundary and the admin report service drops the
two coordinate keys, so an administrator cannot see another user's precise position. The owner's own
endpoints keep the coordinates, because they are the owner's own.

### Step 10 — the auth notices say where

The administrator's registration and sign-in emails now state the event's **approximate place**. The
browser resolves its position to a place (the same `/locations/reverse` lookup the Location page
uses), sends only `{name, city, state, country, pincode}` as `client_location` on `/register` or
`/login`, and the backend stores it on the `login_events` row and renders it in the notice.

| Notice | Carries |
| --- | --- |
| New-user registration | Name, Email, **Location / City / State / Country / Pincode**, Date, Time |
| User sign-in | Name, Email, **Location / City / State / Country / Pincode**, Source (device · IP), Date, Time |

**PRIVACY.** The coordinates are used only for the reverse-geocode and are discarded — they are never
stored on the tracking row and never appear in the email. When the browser refuses permission, times
out, or the lookup fails, the notice reads *“Location unavailable”*; no place is invented.

Every step is conservative: an unknown place is a `404`, an out-of-scope place is a `403`, and a
place with no mapped water is reported as **unavailable** rather than assigned a plausible source.
The water source, the nearby sources and their distances all come from real OpenStreetMap data;
the rain outlook comes from a live weather forecast; the risks, the risk category and the default
readings are the backend's own tables. No risk reason or default reading is invented — when there
is no reliable basis the page says so. The prediction itself is unchanged — `/locations/parameters`
only pre-fills the form, which the user still reviews and submits themselves.

## Build phases

| Phase | Scope | State |
| --- | --- | --- |
| **1** | Architecture, configuration, schema, scaffolding, both apps booting | **Complete** |
| 2 | Auth logic, prediction pipeline, alerts, dashboard aggregates | Pending |
| 3 | Random Forest training on the potability dataset, model artifact | Pending |
| 4 | Aqua AI LLM integration and tool execution | Pending |
| 5 | Testing, hardening, deployment | Pending |

Phase 1 deliberately left `services/*` as documented stubs raising `NotImplementedError` with
final signatures. That is why `GET /dashboard/parameters` is already implemented (66 lines of
real, complete logic deriving metadata from the shared constants) while `run_prediction()` is
not — the contract is fixed so the next phase fills bodies without reshaping the architecture.
