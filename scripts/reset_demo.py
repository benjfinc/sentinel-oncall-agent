"""Restore the demo to a clean, healthy state for the next take (via Composio).

Usage:
    python -m scripts.reset_demo

Writes the known-good app/logic.py back to the default branch. Run this between
recording takes so every run starts from green.
"""

from __future__ import annotations

import base64

from agent import tool_slugs as T
from agent.composio_client import execute_tool, get_client
from agent.config import settings
from scripts._demo_content import DEMO_FILE_PATH, HEALTHY_LOGIC


def _current_blob_sha() -> str:
    client = get_client()
    res = client.tools.execute(
        T.GITHUB_GET_CONTENT,
        arguments={
            "owner": settings.repo_owner,
            "repo": settings.repo_name,
            "path": DEMO_FILE_PATH,
            "ref": settings.default_branch,
        },
        user_id=settings.composio_user_id,
    )
    data = res.get("data", res) if isinstance(res, dict) else {}
    return data.get("sha", "") if isinstance(data, dict) else ""


def main() -> None:
    blob_sha = _current_blob_sha()
    encoded = base64.b64encode(HEALTHY_LOGIC.encode("utf-8")).decode("ascii")
    args = {
        "owner": settings.repo_owner,
        "repo": settings.repo_name,
        "path": DEMO_FILE_PATH,
        "message": "chore: restore healthy compute (demo reset)",
        "content": encoded,
        "branch": settings.default_branch,
    }
    if blob_sha:
        args["sha"] = blob_sha

    execute_tool("setup-reset", "reset_demo", T.GITHUB_UPSERT_FILE, args)
    print(f"✅ Restored {settings.repo_full_name()}:{DEMO_FILE_PATH} to healthy.")
    print("   Ready for a clean take.")


if __name__ == "__main__":
    main()
