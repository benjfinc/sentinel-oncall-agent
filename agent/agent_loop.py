"""Pure LLM agentic loop (alternative to the deterministic pipeline).

Here Claude itself drives the whole remediation by calling Composio GitHub/Slack/
Linear tools in a loop until it decides the incident is resolved. This is the
"fully autonomous agent" story. It is higher-variance than `pipeline.run_incident`
(the model chooses the order of operations), so the pipeline remains the
recommended path for recorded demos. Both use Composio as the execution layer.

Enable with TRIGGER_MODE=agentic (see server.py).
"""

from __future__ import annotations

import json

from . import tool_slugs as T
from . import tracing
from .composio_client import get_client, get_tools
from .config import settings

SYSTEM = """You are Sentinel, an autonomous on-call SRE agent. A production
service on the GitHub repo {repo} just started throwing errors. Resolve the
incident end to end WITHOUT asking for human approval.

Do this:
1. Post to Discord channel ID {channel} that you are investigating.
2. List the {limit} most recent commits on `{branch}`.
3. Identify the single commit most likely to have caused the error (use commit
   messages and changed files). Briefly state your reasoning in Slack.
4. Revert the offending file to its previous (parent-commit) content on a NEW
   branch named `sentinel/revert-<short-sha>`, then open a pull request into
   `{branch}`.
5. Poll the PR's check runs until they complete. Only proceed if CI succeeds.
6. Once CI is green, MERGE the pull request. Do not ask permission — this is
   your job.
7. Post a concise postmortem to Slack.
8. Create a Linear issue (team {team}) for human follow-up.

Rules: never wait for confirmation; if a tool fails, retry once with adjusted
inputs then continue; keep Slack messages short. When fully done, reply with a
final text summary beginning with "INCIDENT RESOLVED".
"""


def run_incident_agentic(error_title: str, error_detail: str = "") -> dict:
    incident_id = tracing.start_incident("agentic", error_title)
    client = get_client()
    tools = get_tools(T.AGENTIC_LOOP_TOOLS)

    system = SYSTEM.format(
        repo=settings.repo_full_name(),
        channel=settings.discord_channel_id,
        branch=settings.default_branch,
        limit=settings.commit_scan_limit,
        team=settings.linear_team_id,
    )
    messages = [
        {
            "role": "user",
            "content": (
                f"Production incident detected.\n"
                f"Error: {error_title}\nDetail: {error_detail}\n"
                f"Repo: {settings.repo_full_name()} (branch {settings.default_branch}).\n"
                f"Resolve it now."
            ),
        }
    ]

    max_turns = 24
    for turn in range(max_turns):
        response = client.messages.create(
            model=settings.model,
            max_tokens=settings.max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            final = "".join(
                b.text for b in response.content if getattr(b, "type", None) == "text"
            )
            tracing.log_event(incident_id, "agentic_final", "info", response=final, ok=True)
            tracing.finish_incident(incident_id, "resolved", final[:500])
            return {"incident_id": incident_id, "status": "resolved", "final": final}

        tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        for b in tool_blocks:
            tracing.log_event(
                incident_id, f"turn{turn}", "tool",
                tool_slug=b.name, request=b.input, note="llm-initiated",
            )

        results = client.provider.handle_tool_calls(
            user_id=settings.composio_user_id, response=response
        )

        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_blocks[i].id,
                        "content": json.dumps(result, default=str),
                    }
                    for i, result in enumerate(results)
                ],
            }
        )

    tracing.finish_incident(incident_id, "failed", "max turns exceeded")
    return {"incident_id": incident_id, "status": "failed", "final": "max turns exceeded"}
