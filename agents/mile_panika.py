"""Agent 3 — Mile Panika 📊
Campaign Strategy & Analytics.

Responsibilities:
  * Designs campaign strategy (channels, cadence, sequencing, KPIs) and
    attaches templates produced by Pero Dactil.
  * Ingests performance metrics, computes rates, checks DATA HEALTH
    (impossible values, missing baselines, deliverability red flags).
  * Produces verdicts + recommendations and logs everything to the database.
"""
from __future__ import annotations

import time
from typing import Any

from agents import database as db
from agents.knowledge import load_knowledge_base

AGENT_NAME = "Mile Panika"
ROLE = "Campaign Strategy & Analytics / Data Health"


def design_campaign(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a campaign strategy in the DB.

    payload keys: name (required), objective, audience, company_id,
                  template_ids (list), channel, daily_goal
    """
    start = time.time()
    name = (payload.get("name") or "").strip()
    if not name:
        db.log_run(AGENT_NAME, "design_campaign", payload, {}, status="error", error="missing 'name'")
        raise ValueError("design_campaign requires a 'name'")

    kb = load_knowledge_base()
    benchmarks = kb.get("benchmarks", {}).get("email", {})
    company = db.get_company(int(payload["company_id"])) if payload.get("company_id") else None
    templates = db.list_templates()
    chosen_ids = payload.get("template_ids") or [t["id"] for t in templates[:2]]

    tone = (company or {}).get("identity", {}).get("communication_tone", "professional")
    industry = (company or {}).get("industry", "general B2B")

    strategy = {
        "framework": "AIDA primary / PAS fallback (A/B split 70/30)",
        "channel_mix": [payload.get("channel", "email"), "LinkedIn touch on day 4"],
        "cadence": ["Day 0: initial email", "Day 3: follow-up #1", "Day 8: value drop", "Day 14: breakup"],
        "send_window": "Tue-Thu, 09:00-11:00 local (per learnings/timing)",
        "personalization_level": "high — use researched client BIO fields",
        "tone": tone,
        "target_audience": payload.get("audience", f"{industry} decision makers"),
        "kpis": {
            "open_rate_target": max(0.35, benchmarks.get("open_rate_min", 0.30) + 0.05),
            "reply_rate_target": benchmarks.get("reply_rate_good", 0.05),
            "bounce_ceiling": benchmarks.get("bounce_max", 0.02),
        },
        "daily_goal": int(payload.get("daily_goal", 50)),
    }

    record = {
        "name": name,
        "objective": payload.get("objective", "book qualified demos"),
        "channel": payload.get("channel", "email"),
        "audience": payload.get("audience", ""),
        "strategy": strategy,
        "template_ids": chosen_ids,
        "company_id": (company or {}).get("id") or payload.get("company_id"),
        "status": "planned",
    }
    campaign_id = db.save_campaign(record)
    out = {"campaign_id": campaign_id, **record}
    db.log_run(AGENT_NAME, "design_campaign", payload, out, duration_ms=int((time.time() - start) * 1000))
    return out


def _rate(num: float, den: float) -> float | None:
    if den is None or den <= 0:
        return None
    return round(num / den, 4)


def analyze_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """Record + analyze campaign metrics and run data-health checks.

    payload keys: campaign_id (required), sent, opens, clicks, replies,
                  bounces, unsubscribes, conversions
    """
    start = time.time()
    campaign_id = payload.get("campaign_id")
    if not campaign_id:
        db.log_run(AGENT_NAME, "analyze_metrics", payload, {}, status="error", error="missing 'campaign_id'")
        raise ValueError("analyze_metrics requires a 'campaign_id'")

    m = {k: int(payload.get(k, 0) or 0) for k in
         ("sent", "opens", "clicks", "replies", "bounces", "unsubscribes", "conversions")}
    db.record_metrics(int(campaign_id), m)

    kb = load_knowledge_base()
    bench = kb.get("benchmarks", {}).get("email", {})

    rates = {
        "open_rate": _rate(m["opens"], m["sent"]),
        "click_rate": _rate(m["clicks"], m["sent"]),
        "reply_rate": _rate(m["replies"], m["sent"]),
        "bounce_rate": _rate(m["bounces"], m["sent"]),
        "unsubscribe_rate": _rate(m["unsubscribes"], m["sent"]),
        "conversion_rate": _rate(m["conversions"], m["sent"]),
        "click_to_open": _rate(m["clicks"], m["opens"]),
    }

    issues: list[str] = []
    warnings: list[str] = []

    # ---- Data health checks ----
    if m["sent"] <= 0:
        issues.append("sent must be > 0 — all rates are undefined; check the export source.")
    for field in ("opens", "clicks", "replies", "bounces", "unsubscribes", "conversions"):
        if m[field] < 0:
            issues.append(f"{field} is negative ({m[field]}) — impossible value, fix the pipeline.")
        elif m["sent"] > 0 and m[field] > m["sent"]:
            issues.append(f"{field} ({m[field]}) exceeds sent ({m['sent']}) — corrupted or double-counted metric.")
    if m["clicks"] > m["opens"]:
        warnings.append("clicks exceed opens — likely broken open-tracking (image proxy blocking).")
    if m["conversions"] > m["clicks"]:
        warnings.append("conversions exceed clicks — attribution may be over-crediting email.")
    if rates["bounce_rate"] is not None and rates["bounce_rate"] > bench.get("bounce_max", 0.02):
        issues.append(f"bounce rate {rates['bounce_rate']:.1%} above safe ceiling — list hygiene problem, pause sending.")
    if rates["unsubscribe_rate"] is not None and rates["unsubscribe_rate"] > bench.get("unsubscribe_max", 0.005):
        warnings.append(f"unsubscribe rate {rates['unsubscribe_rate']:.1%} high — review audience targeting.")

    # ---- Performance verdict ----
    def band(value: float | None, good: float, minimum: float) -> str:
        if value is None:
            return "no_data"
        if value >= good:
            return "good"
        if value >= minimum:
            return "ok"
        return "underperforming"

    verdict = {
        "open_rate": band(rates["open_rate"], bench.get("open_rate_good", .45), bench.get("open_rate_min", .30)),
        "click_rate": band(rates["click_rate"], bench.get("click_rate_good", .08), bench.get("click_rate_min", .025)),
        "reply_rate": band(rates["reply_rate"], bench.get("reply_rate_good", .05), bench.get("reply_rate_min", .015)),
    }

    recs: list[str] = []
    if verdict["open_rate"] == "underperforming":
        recs.append("Test question-style subject lines under 50 chars (learnings/subject_lines).")
    if verdict["click_rate"] == "underperforming":
        recs.append("Reduce to ONE clear CTA per email (learnings/cta).")
    if verdict["reply_rate"] == "underperforming":
        recs.append("Add first-line personalization from Ladi Dadi's client BIO profiles.")
    if not rates["open_rate"] and m["sent"] > 0:
        recs.append("No opens recorded — verify tracking pixel / sender reputation before scaling volume.")
    if not recs:
        recs.append("Metrics healthy — maintain cadence and consider +25% send volume next week.")

    health_score = 100 - len(issues) * 25 - len(warnings) * 10
    out = {
        "campaign_id": int(campaign_id),
        "raw": m,
        "rates": rates,
        "verdict": verdict,
        "data_health": {"score": max(0, health_score), "issues": issues, "warnings": warnings},
        "recommendations": recs,
    }
    db.log_run(AGENT_NAME, "analyze_metrics", payload, out, duration_ms=int((time.time() - start) * 1000))
    return out


def dashboard_summary() -> dict[str, Any]:
    """Aggregate numbers for the live preview UI."""
    campaigns = db.list_campaigns()
    per_campaign = []
    for c in campaigns:
        metric = db.latest_metric(c["id"])
        analysis = None
        if metric:
            fake_payload = {"campaign_id": c["id"], **{k: metric.get(k, 0) for k in
                            ("sent", "opens", "clicks", "replies", "bounces", "unsubscribes", "conversions")}}
            analysis = analyze_metrics(fake_payload)
        per_campaign.append({"campaign": c, "latest_metric": metric, "analysis": analysis})
    return {
        "companies": db.list_companies(),
        "clients": db.list_clients(),
        "templates": db.list_templates(),
        "campaigns": per_campaign,
        "learnings": db.get_learnings(),
        "runs": db.recent_runs(30),
    }
