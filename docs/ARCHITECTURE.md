# AquaGuard AI — Architecture

## Layer map

```
┌──────────────────────┐
│  PRESENTATION — React 18 + Vite + Tailwind                           │
│  pages/ · components/ · routes/ · context/ · hooks/                  │
│  Talks to the backend only through api/ (Axios + JWT interceptor).   │
└───────────────────────────────┬──────────────────────┘
                                │ HTTPS / JSON  (Bearer <access token>)
┌───────────────────────────────▼──────────────────────┐
│  API — Flask blueprints under /api/v1                                │
│  routes/  auth · predictions · dashboard · alerts · ai · profile     │
│  Responsibility: HTTP contract only. Parses/validates, delegates.    │
└───────────────────────────────┬──────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────┐
│  APPLICATION — services/                                             │
│  auth_service · prediction_service · alert_service ·                 │
│  dashboard_service · profile_service · ai_service                    │
│  Responsibility: workflows, transactions, ownership checks.          │
└──────┬────────────────┬──────────────────────────────┘
       │                                │
┌──────▼───────────────┐   ┌────────────▼─────────────────────────────┐
│  ML — app/ml/        │   │  AI — app/ai/                            │
│  preprocessing       │   │  client   (LLM transport)                │
│  model_loader        │   │  prompts  (system + context assembly)    │
│  predictor           │   │  tool_runner (controlled tool dispatch)  │
│  train · evaluate    │   └────────────┬─────────────────────────────┘
└──────┬───────────────┘                │
       │                                │
┌──────▼────────────────▼──────────────────────────────┐
│  DATA — models/ (SQLAlchemy) + MySQL 8                               │
│  users · refresh_tokens · water_samples · predictions ·              │
│  prediction_history · alerts · ai_conversations · ai_messages        │
└──────────────────────┘
```

## Why these boundaries

**Routes never contain business logic.** A route reads the request, calls one service
function, and serialises the result. This is what lets `run_prediction()` be called just as
easily from `POST /api/v1/predictions` as from Aqua AI's `run_prediction` tool — one
implementation, two entry points, no duplicated logic.

**Services are the only place that touches the ORM and the ML layer together.** The
prediction workflow (validate → preprocess → infer → persist → alert) is a transaction. If it
lives in a route, splitting it across HTTP and the chatbot is impossible.

**`WaterSample` is separate from `Prediction`.** Raw measurements and model output have
different lifecycles. Retraining the model must re-score stored samples without asking the
user to re-enter data, which requires the two to be distinct rows.

**`PredictionHistory` is a projection, not a second source of truth.** History, export and
Aqua AI's summary tools are read-heavy; joining `predictions → water_samples → users` on every
page load is wasteful. The service writes this flattened row in the *same transaction* that
writes the prediction, so the two cannot diverge.

**`FEATURE_NAMES` and `FEATURE_BOUNDS` live in `constants.py`.** The validator, the
preprocessing step, the training script, the served `/dashboard/parameters` metadata and the
frontend form all derive from that one tuple. Column order is taken from it, never from the
incoming payload — a reordered request cannot silently scramble model inputs.

**Aqua AI proposes; the application executes.** The model may only name a tool from the
catalogue in `utils/ai_tools.py`. `ai/tool_runner.resolve_tool()` rejects anything else, so a
hallucinated function name is refused before it can act. `navigate_to_page` is executed
client-side through React Router; data tools run server-side under the caller's own JWT.

## Request lifecycle — a prediction

```
1.  Predict.jsx        user submits the form
2.  api/index.js       predictionApi.create(features)
3.  api/client.js      attaches Bearer token, POST /api/v1/predictions
4.  prediction_routes  @jwt_required() rejects anonymous callers
5.  prediction_service
      ├─ validate_water_quality_payload()   → 422 with per-field errors, or clean floats
      ├─ preprocessing.preprocess_input()   → 1×9 DataFrame in canonical order
      ├─ predictor.predict()                → class, probabilities, confidence, risk level
      ├─ INSERT water_samples
      ├─ INSERT predictions
      ├─ INSERT prediction_history          (same transaction)
      └─ alert_service.raise_for_prediction()  → INSERT alerts when unsafe
6.  Response           { success, data: { label, confidence, risk_level, ... } }
7.  Dashboard/History  read back from MySQL; the alert bell badge updates
```

## Token strategy

Access tokens are short-lived (30 min) and carried in the `Authorization` header.
Refresh tokens are long-lived (7 days) and **persisted as a SHA-256 digest** in
`refresh_tokens`, so logout and password changes can genuinely revoke them — a
stateless-only JWT setup cannot.

The Axios response interceptor performs one transparent refresh-and-replay on a 401, using a
single in-flight promise so a burst of concurrent 401s triggers exactly one refresh call.

## Failure behaviour

No mock data exists anywhere in this codebase. When a dependency is unavailable the system
says so:

| Condition | Response |
| --- | --- |
| No trained model artifact | `503 MLModelError` naming the expected path and the train command |
| MySQL credentials wrong | `503` on `/health/database` with the driver's message in the log |
| LLM provider unconfigured | Aqua AI reports the assistant is unavailable — it never fabricates a reply |
| Unknown Aqua AI tool requested | `403 ForbiddenError` listing the tools that do exist |
| Invalid parameter values | `422` with an error for every offending field at once |
