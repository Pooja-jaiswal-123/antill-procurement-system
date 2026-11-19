# APPROACH.md

**AI tools used**

- _Inside the app:_ Groq API (model set by `GROQ_MODEL`) extracts chat fields and converts policy amendments/descriptions into policy JSON. Everything it produces is validated, shown as a plain-language diff, and requires human approval. Chat matching, procurement decisions, ranking, and consolidation remain deterministic code.

**Architecture:** FastAPI + SQLite backend, Next.js (React) frontend that proxies `/api` to the backend. `app/engine` is a pure module (lines + master data + policy list → decisions), no web or DB imports, so it is unit-testable and reusable from the API, CLI or tests.

**Flow:** PR lines → item resolution → validation → clubbing → per requirement: contract/ceiling, valuation, preferred list → ordered policy rules (first match) → PO consolidation → rows. Policy version is picked per requirement date.

**Testing:** `cd backend && pytest` — synthetic unit tests (clubbing, ceilings, blocked suppliers, consolidation, amendment with a new rule and effective date) + worked-example tests when kit data is in `data/`.

# Approach

- The chat and policy features use Groq only for extraction and conversion. Groq configuration is controlled by `GROQ_API_KEY`, `GROQ_MODEL`, and `GROQ_API_URL`.
- Groq output is parsed and validated before use. Chat item matching, procurement decisions, ranking, and consolidation remain deterministic application code.
