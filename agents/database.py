"""SQLite persistence layer for the Marketing Specialist Agents.

Stores: agent runs, generated email templates, researched company/client
profiles (BIO + identity), campaign strategies and analytics results.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

DB_PATH = os.environ.get(
    "AGENTS_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "agents.db"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit (or roll back) the transaction, always close.

    Every caller uses `with get_conn() as conn:`, so the previous version leaked
    one open SQLite handle per call — this closes them again on exit.
    """
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # commit on success, roll back on exception
            yield conn
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    website TEXT,
    industry TEXT,
    bio TEXT,
    identity_json TEXT,
    sources_json TEXT,
    confidence REAL DEFAULT 0.0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    full_name TEXT NOT NULL,
    role TEXT,
    email TEXT,
    bio TEXT,
    identity_json TEXT,
    sources_json TEXT,
    confidence REAL DEFAULT 0.0,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    tone TEXT,
    goal TEXT,
    audience TEXT,
    variables_json TEXT,
    quality_score REAL DEFAULT 0.0,
    learnings_used_json TEXT,
    status TEXT DEFAULT 'draft',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    objective TEXT,
    channel TEXT,
    audience TEXT,
    strategy_json TEXT,
    template_ids_json TEXT,
    company_id INTEGER,
    status TEXT DEFAULT 'planned',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS campaign_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    sent INTEGER DEFAULT 0,
    opens INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    bounces INTEGER DEFAULT 0,
    unsubscribes INTEGER DEFAULT 0,
    conversions INTEGER DEFAULT 0,
    recorded_at TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    input_json TEXT,
    output_json TEXT,
    status TEXT DEFAULT 'ok',
    error TEXT,
    duration_ms INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    insight TEXT NOT NULL,
    source TEXT,
    times_used INTEGER DEFAULT 0,
    created_at TEXT
);
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT COUNT(*) AS c FROM learnings")
        if cur.fetchone()["c"] == 0:
            seeds = [
                ("subject_lines", "Questions in subject lines lift open rates ~10-15% vs plain statements.", "web/best-practices"),
                ("subject_lines", "Keep subject lines under 50 characters for mobile visibility.", "web/best-practices"),
                ("personalization", "First-line personalization referencing a concrete detail doubles reply rates.", "web/best-practices"),
                ("cta", "A single clear CTA outperforms multiple competing CTAs in cold emails.", "web/best-practices"),
                ("timing", "Tuesday-Thursday mornings show highest B2B engagement.", "web/best-practices"),
                ("deliverability", "Plain-text emails with few links have lower spam-filter risk.", "web/deliverability"),
            ]
            conn.executemany(
                "INSERT INTO learnings (topic, insight, source, created_at) VALUES (?,?,?,?)",
                [(t, i, s, _now()) for t, i, s in seeds],
            )


# ---------- generic helpers ----------

def log_run(agent: str, action: str, inp: dict[str, Any], out: dict[str, Any],
            status: str = "ok", error: str | None = None, duration_ms: int = 0) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_runs (agent, action, input_json, output_json, status, error, duration_ms, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (agent, action, json.dumps(inp, default=str), json.dumps(out, default=str),
             status, error, duration_ms, _now()),
        )
        return int(cur.lastrowid)


def recent_runs(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ---------- companies / clients ----------

def upsert_company(data: dict[str, Any]) -> int:
    now = _now()
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM companies WHERE name = ?", (data["name"],)).fetchone()
        payload = (
            data.get("website"),
            data.get("industry"),
            data.get("bio"),
            json.dumps(data.get("identity", {}), default=str),
            json.dumps(data.get("sources", []), default=str),
            float(data.get("confidence", 0.0)),
            now,
        )
        if existing:
            conn.execute(
                "UPDATE companies SET website=?, industry=?, bio=?, identity_json=?, sources_json=?,"
                " confidence=?, updated_at=? WHERE id=?",
                (*payload, existing["id"]),
            )
            return int(existing["id"])
        cur = conn.execute(
            "INSERT INTO companies (name, website, industry, bio, identity_json, sources_json,"
            " confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (data["name"], payload[0], payload[1], payload[2], payload[3], payload[4], payload[5], now, payload[6]),
        )
        return int(cur.lastrowid)


def list_companies() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM companies ORDER BY updated_at DESC").fetchall()
        return [_hydrate_company(dict(r)) for r in rows]


def get_company(company_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        return _hydrate_company(dict(row)) if row else None


def _hydrate_company(d: dict[str, Any]) -> dict[str, Any]:
    d["identity"] = json.loads(d.pop("identity_json", None) or "{}")
    d["sources"] = json.loads(d.pop("sources_json", None) or "[]")
    return d


def add_client(data: dict[str, Any]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO clients (company_id, full_name, role, email, bio, identity_json,"
            " sources_json, confidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("company_id"),
                data["full_name"],
                data.get("role"),
                data.get("email"),
                data.get("bio"),
                json.dumps(data.get("identity", {}), default=str),
                json.dumps(data.get("sources", []), default=str),
                float(data.get("confidence", 0.0)),
                _now(), _now(),
            ),
        )
        return int(cur.lastrowid)


def list_clients() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["identity"] = json.loads(d.pop("identity_json") or "{}")
            d["sources"] = json.loads(d.pop("sources_json") or "[]")
            out.append(d)
        return out


# ---------- templates ----------

def save_template(data: dict[str, Any]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO email_templates (subject, body, tone, goal, audience, variables_json,"
            " quality_score, learnings_used_json, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                data["subject"], data["body"], data.get("tone", "professional"),
                data.get("goal", "engagement"), data.get("audience", ""),
                json.dumps(data.get("variables", []), default=str),
                float(data.get("quality_score", 0.0)),
                json.dumps(data.get("learnings_used", []), default=str),
                data.get("status", "draft"), _now(),
            ),
        )
        return int(cur.lastrowid)


def list_templates() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM email_templates ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["variables"] = json.loads(d.pop("variables_json") or "[]")
            d["learnings_used"] = json.loads(d.pop("learnings_used_json") or "[]")
            out.append(d)
        return out


# ---------- campaigns & metrics ----------

def save_campaign(data: dict[str, Any]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO campaigns (name, objective, channel, audience, strategy_json,"
            " template_ids_json, company_id, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                data["name"], data.get("objective", ""), data.get("channel", "email"),
                data.get("audience", ""), json.dumps(data.get("strategy", {}), default=str),
                json.dumps(data.get("template_ids", []), default=str), data.get("company_id"),
                data.get("status", "planned"), _now(),
            ),
        )
        return int(cur.lastrowid)


def list_campaigns() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM campaigns ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["strategy"] = json.loads(d.pop("strategy_json") or "{}")
            d["template_ids"] = json.loads(d.pop("template_ids_json") or "[]")
            out.append(d)
        return out


def record_metrics(campaign_id: int, m: dict[str, Any]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO campaign_metrics (campaign_id, sent, opens, clicks, replies,"
            " bounces, unsubscribes, conversions, recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                campaign_id,
                int(m.get("sent", 0)), int(m.get("opens", 0)), int(m.get("clicks", 0)),
                int(m.get("replies", 0)), int(m.get("bounces", 0)), int(m.get("unsubscribes", 0)),
                int(m.get("conversions", 0)), _now(),
            ),
        )
        conn.execute("UPDATE campaigns SET status='measured' WHERE id=?", (campaign_id,))
        return int(cur.lastrowid)


def latest_metric(campaign_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM campaign_metrics WHERE campaign_id=? ORDER BY id DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------- learnings ----------

def get_learnings(topic: str | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if topic:
            rows = conn.execute(
                "SELECT * FROM learnings WHERE topic=? ORDER BY times_used DESC", (topic,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM learnings ORDER BY topic, times_used DESC").fetchall()
        return [dict(r) for r in rows]


def touch_learning(learning_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE learnings SET times_used = times_used + 1 WHERE id=?", (learning_id,))


def add_learning(topic: str, insight: str, source: str = "agent") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO learnings (topic, insight, source, created_at) VALUES (?,?,?,?)",
            (topic, insight, source, _now()),
        )
        return int(cur.lastrowid)
