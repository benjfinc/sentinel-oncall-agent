"""Sentinel HTTP server.

Endpoints:
  GET  /                     status page + buttons (Simulate incident, view logs)
  GET  /health               liveness
  POST /incident-webhook     real Sentry alert webhook -> kicks off remediation
  POST /simulate-incident    deterministic backup trigger (for clean demo takes)
  GET  /logs                 execution-trace dashboard (the deliverable)
  GET  /logs/{incident_id}   per-incident trace detail
  GET  /api/incidents        JSON list of incidents
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import tracing
from .config import settings

TRIGGER_MODE = os.getenv("TRIGGER_MODE", "pipeline")  # 'pipeline' | 'agentic'

app = FastAPI(title="Sentinel — Autonomous On-Call Agent", version="1.0.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@app.on_event("startup")
def _startup() -> None:
    tracing.init_db()


def _kick_off(error_title: str, error_detail: str, trigger_source: str) -> None:
    """Run remediation in a background thread so webhooks return immediately."""

    def _run() -> None:
        if TRIGGER_MODE == "agentic":
            from .agent_loop import run_incident_agentic

            run_incident_agentic(error_title, error_detail)
        else:
            from .pipeline import run_incident

            run_incident(error_title, error_detail, trigger_source)

    threading.Thread(target=_run, daemon=True).start()


@app.get("/health")
def health() -> dict:
    problems = settings.validate()
    return {"status": "ok" if not problems else "degraded", "config_problems": problems}


@app.post("/incident-webhook")
async def incident_webhook(request: Request) -> JSONResponse:
    """Receive a Sentry issue-alert webhook and trigger remediation.

    Sentry's payload shape varies by integration; we extract a title defensively
    and fall back to a generic title so the agent always has something to act on.
    """
    payload: Any = {}
    try:
        payload = await request.json()
    except Exception:
        pass

    error_title, error_detail = _parse_sentry(payload)
    _kick_off(error_title, error_detail, trigger_source="sentry")
    return JSONResponse({"accepted": True, "error_title": error_title})


@app.post("/simulate-incident")
async def simulate_incident(request: Request) -> JSONResponse:
    """Deterministic backup trigger. Body (optional): {title, detail}."""
    body: Any = {}
    try:
        body = await request.json()
    except Exception:
        pass
    title = (body or {}).get("title") or "ZeroDivisionError in /compute"
    detail = (body or {}).get("detail") or (
        "GET /compute 500 — unhandled exception raised from app/logic.py:compute"
    )
    _kick_off(title, detail, trigger_source="simulated")
    return JSONResponse({"accepted": True, "error_title": title})


def _parse_sentry(payload: dict) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "Production error detected", ""
    data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
    event = data.get("event", {}) if isinstance(data.get("event"), dict) else {}
    issue = data.get("issue", {}) if isinstance(data.get("issue"), dict) else {}

    title = (
        event.get("title")
        or issue.get("title")
        or payload.get("message")
        or "Production error detected"
    )
    culprit = event.get("culprit") or issue.get("culprit") or ""
    detail = f"{event.get('metadata', {})}".strip() if event.get("metadata") else ""
    detail = (detail + (f" culprit={culprit}" if culprit else "")).strip()
    return str(title), detail


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    incidents = tracing.list_incidents(limit=25)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "repo": settings.repo_full_name(),
            "model": settings.model,
            "trigger_mode": TRIGGER_MODE,
            "incidents": incidents,
            "config_problems": settings.validate(),
        },
    )


@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request) -> HTMLResponse:
    incidents = tracing.list_incidents(limit=50)
    return templates.TemplateResponse(
        "logs.html", {"request": request, "incidents": incidents}
    )


@app.get("/logs/{incident_id}", response_class=HTMLResponse)
def logs_detail(request: Request, incident_id: str) -> HTMLResponse:
    events = tracing.get_events(incident_id)
    incident = next(
        (i for i in tracing.list_incidents(limit=200) if i["id"] == incident_id), None
    )
    return templates.TemplateResponse(
        "incident.html",
        {"request": request, "incident": incident, "events": events, "incident_id": incident_id},
    )


@app.get("/api/incidents")
def api_incidents() -> JSONResponse:
    return JSONResponse(tracing.list_incidents(limit=100))
