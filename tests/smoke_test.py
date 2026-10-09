"""Dependency-free smoke tests for the Marketing Specialist Agents.

Run:  python tests/smoke_test.py
Uses a throwaway SQLite file, never touches data/agents.db and makes no
network calls (web learning is exercised only through its offline fallback).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Point the persistence layer at a temp DB *before* importing the app.
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="agents-smoke-"), "smoke.db")
os.environ["AGENTS_DB"] = _TMP_DB

from agents import database as db                     # noqa: E402
from agents import ladi_dadi, mile_panika, pero_dactil  # noqa: E402
from agents.knowledge import knowledge_base_path, load_knowledge_base  # noqa: E402
from app import app                                   # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail and not condition else ""))


def counts() -> dict[str, int]:
    conn = sqlite3.connect(_TMP_DB)
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("companies", "clients", "email_templates", "campaigns",
                      "campaign_metrics", "agent_runs", "learnings")
        }
    finally:
        conn.close()


# ---------------------------------------------------------------- knowledge base

def test_knowledge_base_loads_from_repo() -> None:
    check("knowledge_base.json resolves to a real file", knowledge_base_path() is not None,
          f"path={knowledge_base_path()}")
    kb = load_knowledge_base()
    check("knowledge base is not empty (regression: hardcoded /workspace path)", bool(kb))
    for section in ("frameworks", "tones", "goals", "benchmarks"):
        check(f"knowledge base has '{section}'", section in kb and bool(kb.get(section)))
    check("load_knowledge_base() is cached", load_knowledge_base() is kb)


# ------------------------------------------------------------------- connection

def test_connections_are_closed() -> None:
    with db.get_conn() as conn:
        conn.execute("SELECT 1")
    try:
        conn.execute("SELECT 1")
        closed = False
    except sqlite3.ProgrammingError:
        closed = True
    check("get_conn() closes the SQLite handle on exit (regression: fd leak)", closed)


# ------------------------------------------------------------------------ pages

def test_pages(client) -> None:
    r = client.get("/health")
    body = r.get_json()
    check("GET /health returns 200", r.status_code == 200)
    check("health lists all three agents",
          body.get("agents") == [pero_dactil.AGENT_NAME, ladi_dadi.AGENT_NAME, mile_panika.AGENT_NAME])
    r = client.get("/")
    html = r.get_data(as_text=True)
    check("GET / renders the UI", r.status_code == 200 and "Marketing Specialist Agents" in html)
    check("UI calls the API with relative URLs (proxy-safe)",
          'fetch("/api/dashboard")' in html and "localhost" not in html)


# ------------------------------------------------------------- Pero Dactil

def test_pero(client) -> None:
    r = client.post("/api/pero/generate_template", json={
        "goal": "cold_outreach", "tone": "formal", "learn_from_web": False,
        "first_name": "Maria", "last_name": "Kovac", "title": "Ms",
        "company": "Acme Robotics", "pain_point": "manual inventory reports",
        "area": "warehouse automation", "value_prop": "cut reporting busywork in half",
    })
    check("POST /api/pero/generate_template returns 200", r.status_code == 200)
    res = r.get_json()["result"]
    check("template persisted with an id", isinstance(res.get("template_id"), int))
    check("formal tone pack applied from knowledge base (regression: empty KB)",
          res["body"].startswith("Dear Ms Kovac,"), res["body"].splitlines()[0])
    check("CTA comes from the knowledge base goal pack",
          "15-minute call" in res["body"], res["body"])
    check("framework notes resolved from knowledge base",
          any("Framework: AIDA —" in n and n.strip() != "Framework: AIDA —"
              or "Framework: PAS —" in n and n.strip() != "Framework: PAS —"
              or "Framework: BAB —" in n and n.strip() != "Framework: BAB —"
              for n in res["learnings_used"]), str(res["learnings_used"][:1]))
    check("quality score in range", 0 <= res["quality_score"] <= 100)
    check("merge variables detected", isinstance(res.get("variables"), list))
    check("subject kept under the 50-char learning", len(res["subject"]) <= 50)

    # Blank optional fields must not punch holes in the copy.
    r = client.post("/api/pero/generate_template", json={
        "goal": "follow_up", "tone": "friendly", "learn_from_web": False,
        "first_name": "", "company": "", "pain_point": "", "area": "", "value_prop": "",
    })
    res = r.get_json()["result"]
    check("blank fields fall back to defaults (regression: 'Hi ,')",
          "Hi ," not in res["body"] and ", is " not in res["subject"], res["body"].splitlines()[0])

    # Offline web learning must degrade gracefully, not 500.
    r = client.post("/api/pero/learn_web", json={})
    report = r.get_json().get("report", {})
    check("POST /api/pero/learn_web degrades gracefully offline",
          r.status_code == 200 and set(report) == {"fetched", "failed", "new_insights"})


# ------------------------------------------------------------- Ladi Dadi

def test_ladi(client) -> None:
    r = client.post("/api/ladi/research_company", json={
        "name": "Acme Robotics", "website": "https://acme-robotics.invalid",
        "industry": "technology", "notes": "Series B, sells warehouse robots",
    })
    check("POST /api/ladi/research_company returns 200", r.status_code == 200)
    company = r.get_json()["result"]
    check("company stored with an id", isinstance(company.get("company_id"), int))
    check("unreachable site falls back to the knowledge base profile",
          company["identity"]["source"] == "knowledge_base_fallback")
    check("fallback suggests frameworks from the knowledge base (regression: empty KB)",
          company["identity"]["suggested_frameworks"] == ["AIDA", "PAS"],
          str(company["identity"]["suggested_frameworks"]))
    check("fallback confidence is lowered", 0 < company["confidence"] < 0.5)
    check("provided notes are folded into the BIO", "Series B" in company["bio"])

    r = client.post("/api/ladi/research_company", json={"name": "   "})
    check("missing company name returns 400 (not 500)", r.status_code == 400)
    check("400 body carries an error message", bool(r.get_json().get("error")))

    r = client.post("/api/ladi/research_client", json={
        "full_name": "Maria Kovac", "role": "VP Operations", "company": "Acme Robotics",
        "email": "maria@acme.com", "interests": ["automation", "lean logistics"],
    })
    client_res = r.get_json()["result"]
    check("POST /api/ladi/research_client returns 200", r.status_code == 200)
    check("client linked to the researched company", client_res["company_id"] == company["company_id"])
    check("seniority detected as strategic", client_res["identity"]["decision_style"] == "strategic")
    check("role-derived pain points populated", bool(client_res["identity"]["likely_pain_points"]))
    check("tone inherited from the company profile",
          client_res["identity"]["preferred_tone"] == company["identity"]["communication_tone"])

    r = client.post("/api/ladi/research_client", json={})
    check("missing client name returns 400", r.status_code == 400)


# ------------------------------------------------------------- Mile Panika

def test_mile(client) -> None:
    r = client.post("/api/mile/design_campaign", json={
        "name": "Q4 Acme push", "objective": "book qualified demos", "daily_goal": 75,
    })
    check("POST /api/mile/design_campaign returns 200", r.status_code == 200)
    campaign = r.get_json()["result"]
    cid = campaign["campaign_id"]
    check("campaign stored with an id", isinstance(cid, int))
    check("strategy has cadence + channel mix", bool(campaign["strategy"]["cadence"])
          and bool(campaign["strategy"]["channel_mix"]))
    check("KPI targets come from knowledge-base benchmarks",
          campaign["strategy"]["kpis"]["open_rate_target"] == 0.35)
    check("daily_goal respected", campaign["strategy"]["daily_goal"] == 75)
    check("existing templates auto-attached", isinstance(campaign["template_ids"], list))

    r = client.post("/api/mile/design_campaign", json={})
    check("missing campaign name returns 400", r.status_code == 400)

    healthy = {"campaign_id": cid, "sent": 1000, "opens": 480, "clicks": 90,
               "replies": 55, "bounces": 8, "unsubscribes": 2, "conversions": 12}
    before = counts()
    r = client.post("/api/mile/analyze_metrics", json=healthy)
    check("POST /api/mile/analyze_metrics returns 200", r.status_code == 200)
    analysis = r.get_json()["result"]
    after = counts()
    check("analyze_metrics records exactly one metric row",
          after["campaign_metrics"] - before["campaign_metrics"] == 1)
    check("analyze_metrics logs exactly one agent run",
          after["agent_runs"] - before["agent_runs"] == 1)
    check("rates computed", analysis["rates"]["open_rate"] == 0.48
          and analysis["rates"]["click_to_open"] == 0.1875)
    check("good open rate verdicted as 'good'", analysis["verdict"]["open_rate"] == "good")
    check("clean data scores 100 health", analysis["data_health"]["score"] == 100,
          str(analysis["data_health"]))

    dirty = {"campaign_id": cid, "sent": 100, "opens": 50, "clicks": 80,
             "replies": -5, "bounces": 20, "unsubscribes": 1, "conversions": 90}
    r = client.post("/api/mile/analyze_metrics", json=dirty)
    bad = r.get_json()["result"]
    issues = " ".join(bad["data_health"]["issues"])
    check("negative value flagged as impossible", "replies is negative (-5)" in issues, issues)
    check("bounce ceiling breach flagged", "bounce rate" in issues and "pause sending" in issues)
    check("clicks>opens warns about broken open tracking",
          any("clicks exceed opens" in w for w in bad["data_health"]["warnings"]))
    check("conversions>clicks warns about attribution",
          any("attribution" in w for w in bad["data_health"]["warnings"]))
    check("dirty data lowers the health score", bad["data_health"]["score"] < 50,
          str(bad["data_health"]["score"]))

    # opens > sent is the double-counting / corrupted-export case.
    r = client.post("/api/mile/analyze_metrics", json={
        "campaign_id": cid, "sent": 100, "opens": 150, "clicks": 10,
        "replies": 2, "bounces": 1, "unsubscribes": 0, "conversions": 1,
    })
    overflow_issues = " ".join(r.get_json()["result"]["data_health"]["issues"])
    check("value exceeding sent flagged as corrupted",
          "opens (150) exceeds sent (100)" in overflow_issues, overflow_issues)

    r = client.post("/api/mile/analyze_metrics", json={"campaign_id": cid, "sent": 0})
    zero = r.get_json()["result"]
    check("sent=0 leaves rates undefined", zero["rates"]["open_rate"] is None)
    check("sent=0 flagged as an issue", any("sent must be > 0" in i for i in zero["data_health"]["issues"]))
    check("sent=0 verdicts are no_data", zero["verdict"]["open_rate"] == "no_data")

    r = client.post("/api/mile/analyze_metrics", json={"sent": 10})
    check("missing campaign_id returns 400", r.status_code == 400)


def test_dashboard_is_read_only(client) -> None:
    """Regression: GET /api/dashboard used to insert duplicate metric + run rows."""
    client.get("/api/dashboard")  # warm up
    before = counts()
    for _ in range(3):
        r = client.get("/api/dashboard")
        assert r.status_code == 200, r.status_code
    after = counts()
    check("GET /api/dashboard does not write to the database", before == after,
          f"before={before} after={after}")
    data = r.get_json()["data"]
    check("dashboard returns every section",
          set(data) == {"companies", "clients", "templates", "campaigns", "learnings", "runs"})
    measured = [c for c in data["campaigns"] if c["analysis"]]
    check("dashboard still analyses stored metrics inline", bool(measured))
    latest = measured[0]["latest_metric"]
    check("dashboard analysis matches the stored latest snapshot",
          all(measured[0]["analysis"]["raw"][k] == latest[k] for k in mile_panika.METRIC_FIELDS),
          str(measured[0]["analysis"]["raw"]))
    check("dashboard surfaces learnings", len(data["learnings"]) >= 6)


def test_learnings_reused(client) -> None:
    before = {l["id"]: l["times_used"] for l in db.get_learnings()}
    client.post("/api/pero/generate_template", json={"learn_from_web": False})
    after = {l["id"]: l["times_used"] for l in db.get_learnings()}
    check("generate_template increments times_used on the learnings it applied",
          any(after[k] > v for k, v in before.items() if k in after))


def main() -> int:
    print(f"temp DB: {_TMP_DB}\nknowledge base: {knowledge_base_path()}\n")
    db.init_db()
    client = app.test_client()
    for fn in (test_knowledge_base_loads_from_repo, test_connections_are_closed):
        fn()
    test_pages(client)
    test_pero(client)
    test_ladi(client)
    test_mile(client)
    test_dashboard_is_read_only(client)
    test_learnings_reused(client)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("failed checks:\n  - " + "\n  - ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
