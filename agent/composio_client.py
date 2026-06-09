"""Thin wrapper around the Composio SDK.

Provides:
  - a lazily-initialised Composio client (so importing this module never
    requires keys — important for offline tests), and
  - `execute_tool(...)`, a traced, retrying wrapper over
    `composio.tools.execute(...)` that every remediation step goes through.

All external side effects in Sentinel flow through here, which is what makes
Composio the single execution layer.
"""

from __future__ import annotations

import time
from typing import Any

from . import tracing
from .config import settings

_composio = None  # lazily created singleton


def get_client():
    """Return a Composio client configured with the Anthropic provider.

    Imported lazily so unit tests can run without the SDK or any keys.
    """
    global _composio
    if _composio is None:
        from composio import Composio
        from composio_anthropic import AnthropicProvider

        _composio = Composio(
            provider=AnthropicProvider(),
            api_key=settings.composio_api_key,
        )
    return _composio


def get_tools(tool_slugs: list[str]):
    """Fetch Anthropic-formatted tool schemas for the given slugs."""
    client = get_client()
    return client.tools.get(user_id=settings.composio_user_id, tools=tool_slugs)


class ToolError(RuntimeError):
    """Raised when a Composio tool call fails after all retries."""


def _unwrap(result: Any) -> tuple[bool, Any]:
    """Normalise Composio's result shape into (ok, data)."""
    if isinstance(result, dict):
        if "successful" in result:
            return bool(result.get("successful")), result.get("data", result)
        if "successfull" in result:  # tolerate historical typo in some versions
            return bool(result.get("successfull")), result.get("data", result)
        if "error" in result and result.get("error"):
            return False, result
    return True, result


def _user_id_for(slug: str) -> str:
    """Return the correct Composio user ID for the given tool slug."""
    s = slug.upper()
    if s.startswith("GITHUB_"):
        return settings.composio_user_id_github or settings.composio_user_id
    if s.startswith("LINEAR_"):
        return settings.composio_user_id_linear or settings.composio_user_id
    if s.startswith("DISCORD"):
        return settings.composio_user_id_discord or settings.composio_user_id
    return settings.composio_user_id


def execute_tool(
    incident_id: str,
    step: str,
    slug: str,
    arguments: dict,
    *,
    retries: int | None = None,
) -> Any:
    """Execute one Composio tool, trace it, and retry transient failures.

    Returns the unwrapped data on success; raises ToolError on failure.
    """
    client = get_client()
    user_id = _user_id_for(slug)
    attempts = (settings.tool_retries if retries is None else retries) + 1
    last_err: Any = None

    for attempt in range(1, attempts + 1):
        try:
            raw = client.tools.execute(
                slug,
                arguments=arguments,
                user_id=user_id,
                dangerously_skip_version_check=True,
            )
            ok, data = _unwrap(raw)
            tracing.log_event(
                incident_id,
                step,
                "tool",
                tool_slug=slug,
                request=arguments,
                response=data,
                ok=ok,
                note=f"attempt {attempt}/{attempts}",
            )
            if ok:
                return data
            last_err = data
        except Exception as exc:  # network / SDK error
            last_err = str(exc)
            tracing.log_event(
                incident_id,
                step,
                "error",
                tool_slug=slug,
                request=arguments,
                response=last_err,
                ok=False,
                note=f"exception on attempt {attempt}/{attempts}",
            )
        if attempt < attempts:
            time.sleep(min(2 ** attempt, 8))

    raise ToolError(f"{slug} failed after {attempts} attempt(s): {last_err}")
