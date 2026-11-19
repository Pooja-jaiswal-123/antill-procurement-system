# Corvo Procure — policy-driven PR → PO

Employees raise purchase requests **by chatting**; the system applies the company's procurement policy and decides **PO or sourcing request**. The policy is **data** (versioned, dated, uploadable) — change it without touching code.

```
 Browser ──► Next.js 14 (React UI, :3000) ──/api/* proxy──► FastAPI (:8000) ──► SQLite
                                                              │
                                                 pure decision engine (app/engine)
                                                 Grok API (optional: chat extraction, policy reading)
```

## Tech stack

| Layer    | Choice                                                    | Why                                                                                                                                                                                                                                                                           |
| -------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend | **Next.js 14 (App Router) + React 18**                    | pages per workflow, `/api` proxy to the backend (no CORS)                                                                                                                                                                                                                     |
| Backend  | **FastAPI (Python)**                                      | typed REST API, auto docs at `/docs`                                                                                                                                                                                                                                          |
| Database | **SQLite** (file `backend/data/app.db`, Python `sqlite3`) | zero-setup, one-command run, transactional; tables: items, suppliers, plants, po_history, contracts, policies (versioned), batches, pr_lines, runs, actions (approve/override), audit, chat_sessions. Production path: swap `app/db.py` for Postgres/Supabase (SQL is plain). |
| AI       | **Groq API** (optional)                                   | extracts fields from chat; reads policy amendments. Decisions themselves are deterministic code.                                                                                                                                                                              |
| Tests    | pytest                                                    | 13 unit tests + 17 worked-example tests (run when kit data is present)                                                                                                                                                                                                        |

## Run locally

**Windows (easiest):** `.\run-local.ps1` — finds the kit, copies data, installs, starts both servers, opens the browser.

**Manual:**

```bash
# 1) backend
cd backend && pip install -r requirements.txt
#    copy the kit's CSVs + RC-*.pdf into backend/data/   (not committed)
DATA_DIR=data XAI_API_KEY=xai-... uvicorn app.main:app --port 8000      # PowerShell: $env:DATA_DIR="data"
# 2) frontend (new terminal)
cd frontend && npm install && npm run dev        # http://localhost:3000
```

**Docker:** put the kit files in `backend/data/`, then `docker compose up --build` → http://localhost:3000.

No data on disk? Open **Master data** in the UI and upload all kit files at once (PDF-only contracts are extracted automatically).
`XAI_API_KEY` is optional for chat (rule-based fallback) but required to read policy _documents/descriptions_; pasted policy JSON always works.

## Deploy (hosted link)

- **Backend:** Render/Railway/Fly using `backend/Dockerfile`. Set `XAI_API_KEY`. Free disks are ephemeral — attach a disk and set `DB_PATH=/var/data/app.db`, or re-upload data from **Master data** after a restart.
- **Frontend:** Vercel (root dir `frontend`) or Render. Set env `API_URL=https://<your-backend-url>` **before building** (it is baked into the proxy rewrite).
- `render.yaml` defines both services.

## Screens

1. **Raise a request** — chat intake; matches only real master items, asks for qty/plant/date/urgency, shows a live summary, confirms.
2. **Buyer workspace** — upload a PR batch CSV; stats, filters, requirement table; drawer shows _why_ (rules tried, contracts & ceilings, preferred ranking); **Approve** / **Override (reason required)**; CSV export.
3. **Preferred suppliers** — ranking with reasons for any item/date; CSV export (`item_code,rank,supplier_id,reference_price`, top 3).
4. **Rate contracts** — register + add PDF-only contract (extract → confirm) or manually.
5. **Policy** — upload amendment / describe change / paste JSON → plain-language diff → effective date → approve. Version chosen per requirement date.
6. **Audit log**, **Master data**.

## API (FastAPI, docs at `:8000/docs`)

`POST /api/process-batch` (CSV → decisions; `?format=csv`, `?save=true`, `?policy_version=`) · `GET /api/runs/{id}/export.csv` · `POST /api/batches/{id}/reprocess` · `GET /api/preferred-suppliers.csv?as_of=` · `POST /api/policies/draft` → `/approve` · `POST /api/contracts/extract[?confirm=true]` · `POST /api/chat` · `GET /api/audit`

## Blind-test runbook

**Run 1:** Buyer workspace → upload batch → Export CSV (or `curl -F file=@batch.csv "HOST/api/process-batch?format=csv"`).
**Run 2:** Policy → upload amendment → check diff → Approve → Buyer workspace → _Reprocess_ → Export.
**Preferred:** Preferred suppliers → set date → Export CSV. Put the 3 files in `submission/` and push before 12:00.

## Repo layout

`backend/app/engine/` pure engine (no web/DB): `core.py`, `preferred.py`, `matcher.py` · `backend/app/{main,db,services,policy,chat,llm,contract_pdf}.py` · `backend/policies/policy_v5_0.json` · `backend/tests/` · `frontend/app/*` pages, `frontend/components`, `frontend/lib/api.js` · `DECISIONS.md` · `APPROACH.md` · `docs/sample_amendment_policy_v5_1.json`

# Corvo Procure — policy-driven PR → PO

Employees raise purchase requests **by chatting**; the system applies the company's procurement policy and decides **PO or sourcing request**. The policy is **data** (versioned, dated, uploadable) — change it without touching code.

## Run locally on Windows

### 1. Groq API (optional)

Set the Groq credentials in the project `.env` file:

```dotenv
GROQ_API_KEY=gsk_replace_me
GROQ_MODEL=allam-2-7b
GROQ_API_URL=https://api.groq.com/openai/v1/chat/completions
```

Groq is optional for chat because the app has a rule-based parser. Policy documents require Groq, but pasted/uploaded policy JSON works without an API key.

### 2. Database

For local SQLite, do not set `DATABASE_URL`:

```powershell
$env:DB_PATH="data/app.db"
```

For Neon PostgreSQL, set:

```dotenv
DATABASE_URL=postgresql://username:password@host/database?sslmode=require
```

The backend creates required tables automatically.

### 3. Start the app

```powershell
.\run-local.ps1
```

Open http://localhost:3000. Backend API documentation: http://localhost:8000/docs.

## Groq and database configuration

| Variable       | Default                                           | Purpose                                 |
| -------------- | ------------------------------------------------- | --------------------------------------- |
| `GROQ_API_KEY` | unset                                             | Groq API key                            |
| `GROQ_MODEL`   | `allam-2-7b`                                      | Groq chat model                         |
| `GROQ_API_URL` | `https://api.groq.com/openai/v1/chat/completions` | Groq OpenAI-compatible endpoint         |
| `DATABASE_URL` | unset                                             | Neon/PostgreSQL URL; unset means SQLite |
| `APP_ENV`      | `development`                                     | Application environment                 |

In Docker:

```powershell
Copy-Item .env.example .env
docker compose up --build
```
