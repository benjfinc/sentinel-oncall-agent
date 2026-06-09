"""Verify the Composio tool slugs Sentinel uses are available to your account.

Usage:
    python -m scripts.verify_tools

Lists the GitHub/Slack/Linear tools your Composio user can access and checks the
slugs in agent/tool_slugs.py against them. If a slug doesn't match (e.g. the
toolkit version renamed an action), it prints close alternatives so you can fix
the constant in one place. Run this once after connecting your accounts.
"""

from __future__ import annotations

import difflib

from agent import tool_slugs as T
from agent.composio_client import get_client
from agent.config import settings

EXPECTED = [
    T.GITHUB_LIST_COMMITS, T.GITHUB_GET_COMMIT, T.GITHUB_GET_REF, T.GITHUB_CREATE_REF,
    T.GITHUB_GET_CONTENT, T.GITHUB_UPSERT_FILE, T.GITHUB_CREATE_PR,
    T.GITHUB_LIST_CHECK_RUNS, T.GITHUB_GET_COMBINED_STATUS, T.GITHUB_MERGE_PR,
    T.SLACK_SEND_MESSAGE, T.LINEAR_CREATE_ISSUE,
]


def _available_slugs() -> set[str]:
    client = get_client()
    slugs: set[str] = set()
    for toolkit in T.TOOLKITS:
        try:
            tools = client.tools.get(user_id=settings.composio_user_id, toolkits=[toolkit])
        except Exception as exc:
            print(f"  ! could not list toolkit '{toolkit}': {exc}")
            continue
        for t in tools or []:
            # Anthropic tool schema dicts expose the slug as 'name'.
            name = t.get("name") if isinstance(t, dict) else getattr(t, "name", None)
            if name:
                slugs.add(name)
    return slugs


def main() -> None:
    print(f"Composio user: {settings.composio_user_id}")
    available = _available_slugs()
    if not available:
        print("No tools returned. Are your GitHub/Slack/Linear accounts connected in Composio?")
        return

    print(f"\nChecking {len(EXPECTED)} expected slugs against {len(available)} available:\n")
    ok = True
    for slug in EXPECTED:
        if slug in available:
            print(f"  ✓ {slug}")
        else:
            ok = False
            close = difflib.get_close_matches(slug, available, n=3, cutoff=0.4)
            hint = f"  → did you mean: {', '.join(close)}" if close else "  → no close match found"
            print(f"  ✗ {slug}\n{hint}")

    print("\nAll good — slugs match." if ok else
          "\nSome slugs need updating in agent/tool_slugs.py (see suggestions above).")


if __name__ == "__main__":
    main()
