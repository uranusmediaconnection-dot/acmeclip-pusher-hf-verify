# Marketing Specialist Agents — live preview

A small Flask app that hosts three cooperating marketing agents on top of a shared
SQLite memory. Each agent is a plain Python module with one or two public
functions; `app.py` exposes them as JSON endpoints and `web/templates/index.html`
is a single-page control panel that drives them and renders the shared database.

| Agent | Module | Responsibility |
| --- | --- | --- |
| 📝 **Pero Dactil** | `agents/pero_dactil.py` | Writes scored email templates (AIDA / PAS / BAB), learning from the web and from stored `learnings` first |
| 🕵️ **Ladi Dadi** | `agents/ladi_dadi.py` | Researches companies and contacts into BIO + identity profiles |
| 📊 **Mile Panika** | `agents/mile_panika.py` | Designs campaign strategy, ingests metrics, runs data-health checks |

Shared plumbing:

- `agents/database.py` — SQLite persistence (`companies`, `clients`, `email_templates`,
  `campaigns`, `campaign_metrics`, `agent_runs`, `learnings`). Schema is created and
  seeded on import by `db.init_db()`.
- `agents/knowledge.py` — HTML text extraction, heuristic industry/value-prop analysis,
  best-effort DuckDuckGo search, and `load_knowledge_base()`.
- `knowledge_base.json` — copy frameworks, tone packs, per-goal CTAs and email
  benchmarks. Every agent reads it and degrades to its own defaults if it is missing.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/seed_demo.py --force   # optional: demo dataset
.venv/bin/python app.py                          # http://localhost:7860
```

`python tests/smoke_test.py` runs 65 dependency-free checks against a throwaway
database using the Flask test client — no server, no network.

### Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENTS_DB` | `<repo>/data/agents.db` | SQLite file location |
| `KNOWLEDGE_BASE` | `<repo>/knowledge_base.json` | Knowledge base location |
| `PORT` | `7860` | Port for `python app.py` |

### Offline behaviour

All web access is best-effort. When a fetch fails, Pero Dactil reports the failure in
`web_learning_report` and Ladi Dadi returns a `knowledge_base_fallback` profile with
lowered confidence, so the app stays usable with no outbound network.

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/` | Control panel |
| GET | `/health` | Service + agent names |
| GET | `/api/dashboard` | Everything the agents have produced (read-only) |
| POST | `/api/pero/generate_template` | `learn_from_web` defaults to `true` |
| POST | `/api/pero/learn_web` | Force a web-learning pass |
| POST | `/api/ladi/research_company` | `name` required → else 400 |
| POST | `/api/ladi/research_client` | `full_name` required → else 400 |
| POST | `/api/mile/design_campaign` | `name` required → else 400 |
| POST | `/api/mile/analyze_metrics` | `campaign_id` required → else 400 |

Errors return `{"ok": false, "error": "..."}` with 400 for bad input and 500 for
unexpected failures.

## Fixes in this branch

1. **The knowledge base was never loaded.** `load_knowledge_base()` read a hardcoded
   `/workspace/knowledge_base.json`, so it silently returned `{}` everywhere else. Tone
   packs, goal CTAs, framework notes and Ladi Dadi's suggested frameworks were all
   missing — the `formal` tone rendered as `Hi Maria,` / `Best,` instead of
   `Dear … ,` / `Sincerely,`, and every CTA fell back to `"Worth a quick chat?"`.
   The path is now resolved relative to the repo (overridable via `KNOWLEDGE_BASE`)
   and cached by mtime.
2. **`GET /api/dashboard` corrupted analytics data.** `dashboard_summary()` called
   `analyze_metrics()`, which *writes*: every page refresh inserted a duplicate
   `campaign_metrics` row, appended an `agent_runs` row and flipped the campaign to
   `measured`. The UI refreshes on load and after every action, so the metrics history
   grew without bound. The pure analysis now lives in `evaluate_metrics()`, which
   writes nothing; `analyze_metrics()` keeps the persist-and-log behaviour.
3. **Operator notes were dropped offline.** `research_company()` folded `payload["notes"]`
   into the BIO only on the live-web branch, so the fallback profile discarded them while
   claiming to be built from "the local knowledge base and stated inputs". Notes now apply
   on both paths.
4. **SQLite handles leaked.** `get_conn()` returned a bare connection and no caller closed
   it — one open file handle per database call. It is now a context manager that commits
   (or rolls back) and always closes.
5. **Blank form fields punched holes in the copy.** `_fill()` used `ctx.get(key, default)`,
   which returns `""` for a submitted-but-empty field, producing greetings like `Hi ,`.
   These now fall back on any falsy value, and the greeting is rendered by `_greeting()`
   so an empty `{title}` cannot leave `Dear  Kovac,` behind.
6. **Repo hygiene.** `data/agents.db`, `server.log` and `__pycache__/*.pyc` were tracked
   (the `.gitignore` `*.log` rule cannot apply to an already-tracked file). They are now
   untracked and ignored; `scripts/seed_demo.py` replaces the committed binary blob as the
   source of demo data. Dead code in `search_duckduckgo()` was removed.

## Known limitations

- `web/static/` is declared as Flask's static folder but does not exist; harmless today
  because the UI inlines its CSS/JS, but any `/static/...` asset would 404.
- `search_duckduckgo()` parses flattened page text, so it returns sentence snippets
  rather than ranked result links.
- Template copy is assembled from banks plus heuristics — there is no LLM call anywhere
  in this repo.
