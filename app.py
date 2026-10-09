"""Live preview web app for the three Marketing Specialist Agents.

Run:  python app.py   (or: flask --app app run)
Open: http://localhost:7860
"""
from __future__ import annotations

import traceback

from flask import Flask, jsonify, render_template, request

from agents import database as db
from agents import ladi_dadi, mile_panika, pero_dactil

db.init_db()

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")


# ---------------- pages ----------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------- Pero Dactil ----------------

@app.route("/api/pero/learn_web", methods=["POST"])
def pero_learn_web():
    try:
        report = pero_dactil.learn_from_web()
        return jsonify({"ok": True, "report": report})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/pero/generate_template", methods=["POST"])
def pero_generate():
    payload = request.get_json(silent=True) or {}
    try:
        result = pero_dactil.generate_template(payload)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------- Ladi Dadi ----------------

@app.route("/api/ladi/research_company", methods=["POST"])
def ladi_company():
    payload = request.get_json(silent=True) or {}
    try:
        result = ladi_dadi.research_company(payload)
        return jsonify({"ok": True, "result": result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ladi/research_client", methods=["POST"])
def ladi_client():
    payload = request.get_json(silent=True) or {}
    try:
        result = ladi_dadi.research_client(payload)
        return jsonify({"ok": True, "result": result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------- Mile Panika ----------------

@app.route("/api/mile/design_campaign", methods=["POST"])
def mile_campaign():
    payload = request.get_json(silent=True) or {}
    try:
        result = mile_panika.design_campaign(payload)
        return jsonify({"ok": True, "result": result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/mile/analyze_metrics", methods=["POST"])
def mile_analyze():
    payload = request.get_json(silent=True) or {}
    try:
        result = mile_panika.analyze_metrics(payload)
        return jsonify({"ok": True, "result": result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------- shared data ----------------

@app.route("/api/dashboard")
def dashboard():
    try:
        return jsonify({"ok": True, "data": mile_panika.dashboard_summary()})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "marketing-agents",
                    "agents": [pero_dactil.AGENT_NAME, ladi_dadi.AGENT_NAME, mile_panika.AGENT_NAME]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False)
