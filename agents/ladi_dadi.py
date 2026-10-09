"""Agent 2 — Ladi Dadi 🕵️
Marketing Strategist.

Responsibilities:
  * Researches companies on the web (fetch + parse their site) and builds a
    BIO + brand IDENTITY profile stored in the database.
  * Researches individual clients (contacts) and stores their bio/identity.
  * When the web is unreachable, falls back to the local knowledge base and
    marks confidence accordingly.
"""
from __future__ import annotations

import time
from typing import Any

from agents import database as db
from agents.knowledge import analyze_text, fetch_url, load_knowledge_base

AGENT_NAME = "Ladi Dadi"
ROLE = "Marketing Strategist (Company & Client Research)"


def _fallback_profile(name: str, industry_hint: str | None) -> dict[str, Any]:
    kb = load_knowledge_base()
    industry = industry_hint or "general B2B"
    fw = list(kb.get("frameworks", {}).values())
    return {
        "bio": (
            f"{name} operates in the {industry} space. Live web research was unavailable, "
            f"so this profile is built from the local knowledge base and stated inputs."
        ),
        "identity": {
            "positioning": f"A {industry} company competing on reliability and focus.",
            "suggested_frameworks": [f["name"] for f in fw][:2],
            "communication_tone": "professional",
            "source": "knowledge_base_fallback",
        },
        "sources": ["local://knowledge_base.json"],
        "confidence": 0.35,
    }


def research_company(payload: dict[str, Any]) -> dict[str, Any]:
    """Research a company by name (+ optional website) and persist its profile.

    payload keys: name (required), website, industry, notes
    """
    start = time.time()
    name = (payload.get("name") or "").strip()
    if not name:
        db.log_run(AGENT_NAME, "research_company", payload, {}, status="error", error="missing 'name'")
        raise ValueError("research_company requires a 'name'")

    website = (payload.get("website") or "").strip() or None
    sources: list[str] = []
    analysis: dict[str, Any] = {}
    fetched_ok = False

    if website:
        try:
            page = fetch_url(website, timeout=8)
            sources.append(page["url"])
            analysis = analyze_text(f"{page['title']} {page['text']}")
            fetched_ok = True
        except Exception as e:
            sources.append(f"failed://{website} ({str(e)[:80]})")

    # Also search the web briefly when direct fetch failed or no site given
    if not fetched_ok:
        try:
            from agents.knowledge import search_duckduckgo
            hits = search_duckduckgo(f"{name} company about", max_results=3)
            if hits:
                joined = " ".join(h["snippet"] for h in hits)
                analysis = analyze_text(joined)
                sources.extend(["search://" + name])
                fetched_ok = True
        except Exception:
            pass

    if fetched_ok and analysis:
        vps = analysis.get("value_props") or []
        industry_label = analysis.get("industry_guess") or payload.get("industry") or "its market"
        bio = f"{name} works in {industry_label}."
        if vps:
            bio += " Observed value propositions: " + "; ".join(vps[:2]) + "."
        if payload.get("notes"):
            bio += f" Provided context: {payload['notes']}"
        identity = {
            "positioning": (vps[0] if vps else f"{name} — {analysis.get('industry_guess')} player"),
            "communication_tone": analysis.get("tone", "formal"),
            "keyword_signals": analysis.get("keyword_scores", {}),
            "suggested_frameworks": ["AIDA", "PAS"],
            "source": "live_web",
        }
        confidence = float(analysis.get("confidence", 0.4))
    else:
        fb = _fallback_profile(name, payload.get("industry"))
        bio, identity, confidence = fb["bio"], fb["identity"], fb["confidence"]
        sources = fb["sources"]

    record = {
        "name": name,
        "website": website,
        "industry": payload.get("industry") or analysis.get("industry_guess"),
        "bio": bio,
        "identity": identity,
        "sources": sources,
        "confidence": confidence,
    }
    company_id = db.upsert_company(record)
    out = {"company_id": company_id, **record}
    db.log_run(AGENT_NAME, "research_company", payload, out, duration_ms=int((time.time() - start) * 1000))
    return out


def research_client(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a client (contact) BIO + identity profile.

    payload keys: full_name (required), company / company_id, role, email,
                  linkedin, interests, notes
    """
    start = time.time()
    full_name = (payload.get("full_name") or "").strip()
    if not full_name:
        db.log_run(AGENT_NAME, "research_client", payload, {}, status="error", error="missing 'full_name'")
        raise ValueError("research_client requires a 'full_name'")

    parts = full_name.split()
    first_name = parts[0]
    last_name = parts[-1] if len(parts) > 1 else ""

    company_id = payload.get("company_id")
    company = None
    if company_id:
        company = db.get_company(int(company_id))
    elif payload.get("company"):
        match = next((c for c in db.list_companies()
                      if c["name"].lower() == str(payload["company"]).lower()), None)
        company = match

    tone = (company or {}).get("identity", {}).get("communication_tone", "professional") \
        if company else "professional"

    interests = payload.get("interests") or []
    role = payload.get("role", "")
    concerns = {
        "ceo": ["growth", "reputation", "cash flow"],
        "cto": ["technical debt", "tooling", "security"],
        "cmo": ["pipeline", "brand reach", "attribution"],
        "sales": ["quota", "lead quality", "cycle length"],
        "operations": ["efficiency", "manual work", "reporting"],
    }
    key = (role or "").lower().split()[0] if role else ""
    pain_points = next((v for k, v in concerns.items() if k in key), ["time", "budget"])

    bio = (
        f"{full_name}"
        + (f" ({role})" if role else "")
        + (f" at {company['name']}" if company else (f" at {payload.get('company')}" if payload.get("company") else ""))
        + ". "
        + (payload.get("notes") or f"Focused on {', '.join(interests) if interests else role or 'their core function'}.")
    )

    identity = {
        "first_name": first_name,
        "last_name": last_name,
        "decision_style": "strategic" if any(k in (role or "").lower() for k in ["head", "chief", "vp", "director", "cto", "ceo", "cmo"]) else "hands-on",
        "likely_pain_points": pain_points,
        "interests": interests,
        "preferred_tone": tone,
        "best_contact_area": (company or {}).get("industry", payload.get("area", "growth")),
    }

    record = {
        "company_id": (company or {}).get("id") or company_id,
        "full_name": full_name,
        "role": role,
        "email": payload.get("email"),
        "bio": bio,
        "identity": identity,
        "sources": [payload["linkedin"]] if payload.get("linkedin") else ["provided_input"],
        "confidence": 0.6 if company else 0.45,
    }
    client_id = db.add_client(record)
    out = {"client_id": client_id, **record}
    db.log_run(AGENT_NAME, "research_client", payload, out, duration_ms=int((time.time() - start) * 1000))
    return out
