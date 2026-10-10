"""Seed a demo dataset so the live preview opens with something to look at.

Run:  python scripts/seed_demo.py            (skips if data already exists)
      python scripts/seed_demo.py --force     (wipe data/*.db and rebuild)
      AGENTS_DB=/tmp/x.db python scripts/seed_demo.py

Everything goes through the agents' own public functions, so the demo data is
exactly what the app would produce — no hand-written SQL. Web learning is
disabled so seeding works offline.
"""
from __future__ import annotations

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from agents import database as db                      # noqa: E402
from agents import ladi_dadi, mile_panika, pero_dactil  # noqa: E402

COMPANIES = [
    {"name": "Acme Robotics", "website": "https://acme-robotics.example",
     "industry": "technology", "notes": "Series B, sells warehouse pick-and-place robots"},
    {"name": "Northwind Logistics", "website": "https://northwind-logistics.example",
     "industry": "manufacturing", "notes": "3PL operator, 12 depots, legacy TMS"},
    {"name": "Brightpath Clinics", "website": "https://brightpath.example",
     "industry": "healthcare", "notes": "Outpatient clinic group, 40 locations"},
]

CLIENTS = [
    {"full_name": "Maria Kovac", "role": "VP Operations", "company": "Acme Robotics",
     "email": "maria@acme-robotics.example", "interests": ["automation", "lean logistics"]},
    {"full_name": "Tomas Berg", "role": "CTO", "company": "Northwind Logistics",
     "email": "tomas@northwind-logistics.example", "interests": ["integration", "fleet telemetry"]},
    {"full_name": "Ana Petrova", "role": "Chief Marketing Officer", "company": "Brightpath Clinics",
     "email": "ana@brightpath.example", "interests": ["patient retention", "brand trust"]},
]

TEMPLATES = [
    {"goal": "cold_outreach", "tone": "professional", "first_name": "Maria", "last_name": "Kovac",
     "company": "Acme Robotics", "industry": "technology", "area": "warehouse automation",
     "pain_point": "manual inventory reports", "value_prop": "cut reporting busywork in half",
     "audience": "operations leaders"},
    {"goal": "demo_request", "tone": "formal", "first_name": "Tomas", "last_name": "Berg", "title": "Mr",
     "company": "Northwind Logistics", "industry": "manufacturing", "area": "fleet telemetry",
     "pain_point": "blind spots across 12 depots", "value_prop": "unify depot telemetry in one view",
     "audience": "technical decision makers"},
    {"goal": "follow_up", "tone": "friendly", "first_name": "Ana", "last_name": "Petrova",
     "company": "Brightpath Clinics", "industry": "healthcare", "area": "patient retention",
     "pain_point": "no-show appointments", "value_prop": "recover 1 in 6 missed appointments",
     "audience": "clinic group marketers"},
    {"goal": "re_engagement", "tone": "energetic", "first_name": "Maria", "last_name": "Kovac",
     "company": "Acme Robotics", "industry": "technology", "area": "warehouse automation",
     "pain_point": "stalled pilot", "value_prop": "restart the pilot with a 2-week ramp",
     "audience": "warm but quiet leads"},
]

CAMPAIGNS = [
    # Healthy campaign: strong open/reply rates, clean data.
    {"name": "Q4 Acme push", "objective": "book qualified demos", "company": "Acme Robotics",
     "channel": "email", "audience": "operations leaders in DACH", "daily_goal": 75,
     "metrics": {"sent": 1200, "opens": 590, "clicks": 112, "replies": 68,
                 "bounces": 9, "unsubscribes": 3, "conversions": 21}},
    # Unhealthy campaign: impossible values + deliverability red flags, so the
    # UI shows Mile Panika's data-health verdicts instead of an empty state.
    {"name": "Northwind re-engagement", "objective": "revive stalled conversations",
     "company": "Northwind Logistics", "channel": "email", "audience": "quiet technical leads",
     "daily_goal": 40,
     "metrics": {"sent": 300, "opens": 340, "clicks": 210, "replies": -4,
                 "bounces": 38, "unsubscribes": 9, "conversions": 260}},
    # Planned campaign with no metrics yet.
    {"name": "Brightpath spring newsletter", "objective": "grow patient-programme signups",
     "company": "Brightpath Clinics", "channel": "email", "audience": "existing patients",
     "daily_goal": 0, "metrics": None},
]


def already_seeded() -> bool:
    return bool(db.list_companies() or db.list_templates() or db.list_campaigns())


def seed() -> dict[str, int]:
    company_ids: dict[str, int] = {}
    for c in COMPANIES:
        out = ladi_dadi.research_company({**c, "learn_from_web": False})
        company_ids[c["name"]] = out["company_id"]

    client_count = 0
    for person in CLIENTS:
        ladi_dadi.research_client({**person, "company_id": company_ids.get(person["company"])})
        client_count += 1

    template_ids: list[int] = []
    for spec in TEMPLATES:
        out = pero_dactil.generate_template({**spec, "learn_from_web": False})
        template_ids.append(out["template_id"])

    campaign_count = 0
    for camp in CAMPAIGNS:
        payload = {k: v for k, v in camp.items() if k not in ("company", "metrics")}
        payload["company_id"] = company_ids.get(camp["company"])
        # Attach the first two templates, like the UI does by default.
        payload["template_ids"] = template_ids[:2]
        out = mile_panika.design_campaign(payload)
        campaign_count += 1
        if camp["metrics"]:
            mile_panika.analyze_metrics({"campaign_id": out["campaign_id"], **camp["metrics"]})

    return {"companies": len(company_ids), "clients": client_count,
            "templates": len(template_ids), "campaigns": campaign_count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="delete the existing database and rebuild it from scratch")
    args = parser.parse_args()

    if args.force and os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
        print(f"removed {db.DB_PATH}")

    db.init_db()
    if already_seeded() and not args.force:
        print(f"database already has data ({db.DB_PATH}) — nothing to do. Use --force to rebuild.")
        return 0

    created = seed()
    print(f"seeded into {db.DB_PATH}:")
    for what, n in created.items():
        print(f"  {what:<10} {n}")
    print(f"  learnings  {len(db.get_learnings())} (seeded by init_db)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
