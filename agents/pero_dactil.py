"""Agent 1 — Pero Dactil 📝
Email Template Specialist.

Responsibilities:
  * Writes email templates (subject + body) for a given tone/goal/audience.
  * Learns from the WEB (fetches best-practice pages when reachable) and from
    the DATABASE (stored `learnings` table) before generating templates.
  * Persists every generated template to the database with a quality score.
"""
from __future__ import annotations

import random
import re
import time
from typing import Any

from agents import database as db
from agents.knowledge import fetch_url, load_knowledge_base

AGENT_NAME = "Pero Dactil"
ROLE = "Email Template Specialist"

WEB_LEARNING_SOURCES = [
    "https://blog.hubspot.com/marketing/cold-email-examples",
    "https://www.wordstream.com/blog/ws/2017-02-28/email-marketing-best-practices",
]


def learn_from_web() -> dict[str, Any]:
    """Try to pull fresh insights from known best-practice pages.

    Returns a report of what was learned vs. what failed (offline-safe).
    """
    report = {"fetched": [], "failed": [], "new_insights": 0}
    for url in WEB_LEARNING_SOURCES:
        try:
            page = fetch_url(url, timeout=6)
            text = page["text"].lower()
            report["fetched"].append({"url": url, "title": page["title"], "chars": len(page["text"])})
            # Extract simple heuristic insights from real content
            checks = [
                ("subject_lines", "short subject lines", "Short subject lines performed well on " + url),
                ("personalization", "personaliz", "Personalization is emphasized on " + url),
                ("cta", "call to action", "A single call-to-action is recommended on " + url),
            ]
            for topic, needle, insight in checks:
                if needle in text:
                    existing = {l["insight"] for l in db.get_learnings(topic)}
                    if insight not in existing:
                        db.add_learning(topic, insight, source=url)
                        report["new_insights"] += 1
        except Exception as e:  # offline / blocked — degrade gracefully
            report["failed"].append({"url": url, "error": str(e)[:120]})
    return report


def _gather_database_learnings(goal: str) -> tuple[list[dict[str, Any]], list[int]]:
    """Pull the most relevant stored learnings for this goal."""
    topics = ["subject_lines", "personalization", "cta"]
    if goal in ("re_engagement", "follow_up"):
        topics.append("timing")
    picked: list[dict[str, Any]] = []
    ids: list[int] = []
    for t in topics:
        rows = db.get_learnings(t)
        if rows:
            chosen = rows[0]
            picked.append(chosen)
            ids.append(int(chosen["id"]))
    return picked, ids


_SUBJECT_BANK = {
    "cold_outreach": [
        "Quick question about {company}'s {area}",
        "{first_name}, is {pain_point} on your radar?",
        "Idea for {company} — worth 2 minutes?",
    ],
    "follow_up": [
        "Floating this back up, {first_name}",
        "{first_name}, did my last note get buried?",
        "One more thought for {company}",
    ],
    "newsletter": [
        "{company} Weekly: 3 things that moved the needle",
        "This week in {area}: what actually worked",
    ],
    "re_engagement": [
        "{first_name}, is this still a priority?",
        "Should I close the loop on {pain_point}?",
    ],
    "demo_request": [
        "{first_name}, want to see {company}'s version of this?",
        "A 15-min walkthrough for {company}?",
    ],
}

_BODY_TEMPLATES = {
    "aida": """{greeting}

{attention}

{interest}

{desire}

{action_line}

{signoff}
{sender}""",
    "pas": """{greeting}

{problem}

{agitate}

{solution}

{action_line}

{signoff}
{sender}""",
    "bab": """{greeting}

{before}

{after}

{bridge}

{action_line}

{signoff}
{sender}""",
}


def _fill(goal: str, ctx: dict[str, Any], learnings: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    kb = load_knowledge_base()
    tones = kb.get("tones", {})
    goals = kb.get("goals", {})
    frameworks = kb.get("frameworks", {})

    tone = ctx.get("tone", "professional")
    tone_pack = tones.get(tone, tones.get("professional", {}))
    goal_pack = goals.get(goal, goals.get("cold_outreach", {}))

    first_name = ctx.get("first_name", "{first_name}")
    company = ctx.get("company", "{company}")
    area = ctx.get("area", "growth")
    pain_point = ctx.get("pain_point", "manual reporting")
    value_prop = ctx.get("value_prop", "cutting busywork for lean teams")
    sender = ctx.get("sender", "{sender_name}, {sender_title}")

    used_notes = [l["insight"] for l in learnings]

    subject_pool = _SUBJECT_BANK.get(goal, _SUBJECT_BANK["cold_outreach"])
    subject = random.choice(subject_pool).format(
        first_name=first_name, company=company, area=area, pain_point=pain_point
    )
    # Learning applied: keep subject under 50 chars when possible
    if len(subject) > 50:
        subject = subject[:47].rstrip(" ,;") + "..."

    cta = goal_pack.get("cta", "Worth a quick chat?").format(booking_link="{booking_link}")

    fw_key = random.choice(list(_BODY_TEMPLATES.keys()))
    fw = frameworks.get(fw_key, {"name": fw_key.upper()})

    personal_hook = (
        f"Noticed {company} is focused on {area} — teams like yours usually hit a wall with {pain_point}."
    )

    parts = {
        "greeting": tone_pack.get("greeting", f"Hi {first_name},").format(
            first_name=first_name, title="", last_name=first_name
        ),
        "signoff": tone_pack.get("signoff", "Best,"),
        "sender": sender,
        "action_line": cta,
        # AIDA
        "attention": personal_hook,
        "interest": f"We help {ctx.get('industry', 'companies')} like {company} {value_prop}.",
        "desire": f"Clients typically see results within the first month — happy to share the exact playbook.",
        # PAS
        "problem": f"{pain_point} quietly eats hours every week at growing teams like {company}.",
        "agitate": f"Every month it stays unsolved, it costs roughly one full head-week of {area} work.",
        "solution": f"We {value_prop} — usually live in days, not quarters.",
        # BAB
        "before": f"Today, {company}'s team deals with {pain_point}.",
        "after": "Imagine that handled automatically, with clean reports landing every Monday.",
        "bridge": f"That's exactly what we {value_prop}.",
    }

    body_tpl = _BODY_TEMPLATES[fw_key]
    try:
        body = body_tpl.format(**parts)
    except KeyError as e:
        # Fallback for any unexpected placeholder — never crash the agent.
        body = body_tpl
        for k, v in parts.items():
            body = body.replace("{" + k + "}", str(v))
    notes = [f"Framework: {fw['name']} — {fw.get('notes','')}"] + used_notes
    return subject, body, notes


def score_template(subject: str, body: str) -> float:
    """Heuristic quality score 0-100."""
    score = 50.0
    if 1 <= len(subject) <= 50:
        score += 10
    if "?" in subject:
        score += 5
    words = len(body.split())
    if 50 <= words <= 150:
        score += 15
    elif words > 200:
        score -= 10
    if "{" in body and "}" in body:
        score += 5  # has merge variables
    if body.count("http") <= 2:
        score += 5  # deliverability-friendly
    if body.strip().endswith((".", "!", "?", "{sender}")) or "sender" in body:
        score += 5
    return round(max(0.0, min(100.0, score)), 1)


def generate_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Main entry point for Pero Dactil.

    payload keys: goal, tone, audience, company, industry, first_name,
                  pain_point, value_prop, area, learn_from_web (bool)
    """
    start = time.time()
    goal = payload.get("goal", "cold_outreach")
    web_report = None
    if payload.get("learn_from_web", True):
        web_report = learn_from_web()

    learnings, learning_ids = _gather_database_learnings(goal)
    for lid in learning_ids:
        db.touch_learning(lid)

    subject, body, notes = _fill(goal, payload, learnings)
    quality = score_template(subject, body)

    variables = sorted(set(re.findall(r"\{(\w+)\}", subject + " " + body)))
    record = {
        "subject": subject,
        "body": body,
        "tone": payload.get("tone", "professional"),
        "goal": goal,
        "audience": payload.get("audience", ""),
        "variables": variables,
        "quality_score": quality,
        "learnings_used": notes,
        "status": "draft",
    }
    template_id = db.save_template(record)
    duration_ms = int((time.time() - start) * 1000)

    out = {"template_id": template_id, **record, "web_learning_report": web_report}
    db.log_run(AGENT_NAME, "generate_template", payload, out, duration_ms=duration_ms)
    return out
