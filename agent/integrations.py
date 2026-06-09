"""Slack and Linear actions, backed by Composio tools."""

from __future__ import annotations

from typing import Any

from . import tool_slugs as T
from .composio_client import execute_tool
from .config import settings


def slack_post(incident_id: str, step: str, text: str) -> Any:
    """Post a message to the incident Slack channel."""
    return execute_tool(
        incident_id,
        step,
        T.SLACK_SEND_MESSAGE,
        {"channel": settings.slack_channel, "text": text},
    )


def linear_create_issue(incident_id: str, title: str, description: str) -> dict:
    """Create a Linear follow-up ticket for human review."""
    raw = execute_tool(
        incident_id,
        "linear_followup",
        T.LINEAR_CREATE_ISSUE,
        {
            "team_id": settings.linear_team_id,
            "title": title,
            "description": description,
        },
    )
    url = ""
    if isinstance(raw, dict):
        url = raw.get("url") or raw.get("html_url") or ""
        data = raw.get("data")
        if not url and isinstance(data, dict):
            url = data.get("url", "")
    return {"url": url, "raw": raw}
