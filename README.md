# AquaGuard AI

**AI-Based Water Quality Monitoring & Prediction System**

A production-style full-stack platform that ingests water quality parameters, validates and
preprocesses them, runs a trained **Random Forest classifier** to predict potability, stores the
result in **MySQL**, surfaces it on a **React dashboard**, raises **unsafe alerts**, and exposes an
**Aqua AI** assistant that can answer questions and drive application navigation through
controlled tools.

---

## 1. Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18 + Vite + JavaScript, Tailwind CSS, Axios, React Router, Recharts |
| Backend | Python 3.13 + Flask, REST API, JWT auth, bcrypt password hashing |
| Database | MySQL 8.0 |
| ML | Pandas, NumPy, Scikit-learn (Random Forest Classifier) |
| AI Assistant | Aqua AI — LLM integration with conversation context + controlled app tools |

---

## 2. Repository Layout

```
aquagaurd/
├── backend/                  Flask REST API (application factory + modular packages)
│   ├── app/
│   │   ├── __init__.py       create_app() application factory
│   │   ├── config.py         Environment-driven configuration classes
│   │   ├── extensions.py     Single instances of db / bcrypt / jwt / cors / migrate
│   │   ├── models/           SQLAlchemy ORM models (schema source of truth)
│   │   ├── routes/           Flask blueprints — one module per resource
│   │   ├── services/         Business logic between routes and data/ML layers
│   │   ├── ml/               Model training, loading, preprocessing, inference
│   │   ├── ai/               Aqua AI — LLM client, prompt building, tool registry
│   │   ├── utils/            Cross-cutting helpers (responses, validation, errors)
│   │   └── constants.py      Enumerations and shared literals
│   ├── database/             SQL DDL + seed / init scripts
│   ├── tests/                Pytest suite
│   ├── requirements.txt      Pinned Python dependencies
│   └── run.py                Development entrypoint
│
├── frontend/                 React SPA (Vite)
│   ├── src/
│   │   ├── api/              Axios instance + per-resource API modules
│   │   ├── components/       Reusable presentational + layout components
│   │   ├── pages/            Route-level views
│   │   ├── context/          Auth / theme / Aqua AI providers
│   │   ├── hooks/            Custom React hooks
│   │   ├── routes/           Route table + protected-route guards
│   │   ├── utils/            Formatting, constants, validators
│   │   ├── assets/           Static images / icons
│   │   ├── App.jsx           Root component
│   │   ├── main.jsx          React entrypoint
│   │   └── index.css         Tailwind entry + design tokens
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
│
├── ml/                       Offline training workspace (not shipped at runtime)
│   ├── datasets/             Raw + processed CSV data
│   ├── notebooks/            EDA / experimentation notebooks
│   └── models/               Serialized .pkl artifacts consumed by backend/app/ml
│
├── docs/                     Architecture, API reference, DB design, workflow
├── scripts/                  Dev convenience scripts (setup, db bootstrap)
└── .env.example              Root-level template for shared variables
```

---

## 3. Runtime Workflow

```
User Login
   ↓
Dashboard
   ↓
Enter Water Quality Parameters
   ↓
React Frontend  ──axios/JSON──▶  Flask REST API
                                    ↓
                              Input Validation
                                    ↓
                              Preprocessing
                                    ↓
                          Random Forest ML Model
                                    ↓
                     Prediction + Confidence Score
                                    ↓
                             MySQL Storage
                                    ↓
                     Dashboard / Prediction History
                                    ↓
                             Unsafe Alert
```

The **Aqua AI** assistant runs alongside this flow with conversational context and a registry of
controlled application tools (navigate, summarise history, explain parameters, trigger a
prediction on behalf of the user).

---

## 4. Getting Started

### 4.1 Prerequisites

- Node.js 18+ and npm
- Python 3.11+ (3.13 verified)
- MySQL 8.0 server running locally

### 4.2 Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # then fill in real values
python app.py                    # http://127.0.0.1:5000
```

`python app.py` prints a startup summary with the database password masked, then serves the
API. `python run.py` is an equivalent alternative entrypoint.

Health checks:

```powershell
curl http://127.0.0.1:5000/api/health      # {"success": true, "message": "AquaGuard AI backend is running"}
curl http://127.0.0.1:5000/api/health/db   # MySQL connectivity + server version
python config.py                           # print the resolved configuration (secrets masked)
python -m app.db_check                     # full database readiness report
```

### 4.3 Database

```powershell
mysql -u root -p < database/schema.sql
```

### 4.4 Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev                      # http://localhost:5173
```

---

## 5. Security Notes

- Passwords are hashed with **bcrypt**; plaintext is never persisted or logged.
- JWT access tokens are short-lived; refresh tokens are stored and revocable server-side.
- All secrets come from environment variables — no credentials are committed.
- `.env` files are git-ignored; only `.env.example` templates are tracked.

---

## 6. Status

**Phase 1 — Base architecture and configuration (current).**
Folder structure, configuration, app factory, blueprint registration, DB schema, and frontend
tooling are in place and verified to boot. Feature implementation (auth logic, prediction
endpoints, ML training, Aqua AI tool execution) lands in subsequent phases without changing this
layout.
