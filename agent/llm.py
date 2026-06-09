"""LLM reasoning steps (Anthropic Claude).

Two jobs:
  1. decide_culprit(...) — the one hard reasoning step: given recent commits and
     the error, pick the offending commit + file. Returns structured JSON.
  2. write_postmortem(...) — generate the human-facing Slack postmortem.

The client is created lazily so offline tests can monkeypatch these functions
without needing an API key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import prompts
from .config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


@dataclass
class CulpritDecision:
    culprit_sha: str
    file_path: str
    confidence: float
    reasoning: str


def _format_commits(commits: list[dict]) -> str:
    lines = []
    for c in commits:
        sha = c.get("sha", "")
        msg = (c.get("message") or "").splitlines()[0] if c.get("message") else ""
        files = ", ".join(c.get("files", [])) or "(files unknown)"
        lines.append(f"- {sha}  {msg}\n    files: {files}")
    return "\n".join(lines)


def _extract_text(response: Any) -> str:
    parts = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def decide_culprit(
    commits: list[dict],
    error_title: str,
    error_detail: str,
    branch: str,
) -> CulpritDecision:
    """Ask Claude to choose the offending commit. Returns a CulpritDecision."""
    model = settings.culprit_model or settings.model
    user = prompts.CULPRIT_USER.format(
        error_title=error_title,
        error_detail=error_detail,
        branch=branch,
        commits_block=_format_commits(commits),
    )
    resp = _get_client().messages.create(
        model=model,
        max_tokens=settings.max_tokens,
        system=prompts.CULPRIT_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    data = _parse_json_object(_extract_text(resp))
    return CulpritDecision(
        culprit_sha=str(data["culprit_sha"]),
        file_path=str(data["file_path"]),
        confidence=float(data.get("confidence", 0.0)),
        reasoning=str(data.get("reasoning", "")),
    )


def write_postmortem(
    *,
    error_title: str,
    culprit_sha: str,
    culprit_message: str,
    pr_number: int,
    pr_url: str,
    file_path: str,
    branch: str,
    duration: str,
) -> str:
    user = prompts.POSTMORTEM_USER.format(
        error_title=error_title,
        culprit_sha=culprit_sha,
        culprit_message=culprit_message,
        pr_number=pr_number,
        pr_url=pr_url,
        file_path=file_path,
        branch=branch,
        duration=duration,
    )
    resp = _get_client().messages.create(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=prompts.POSTMORTEM_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return _extract_text(resp)
