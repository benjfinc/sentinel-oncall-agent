"""Break the demo-service by committing the staged bug to main (via Composio).

Usage:
    python -m scripts.break_demo

This commits a divide-by-zero into app/logic.py on the target repo's default
branch. CI on main goes red and /compute starts returning 500s, which (with
Sentry wired) triggers Sentinel. Run scripts.reset_demo to restore.
"""

from __future__ import annotations

import base64

from agent import tool_slugs as T
from agent.composio_client import execute_tool, get_client
from agent.config import settings
from scripts._demo_content import BROKEN_LOGIC, DEMO_FILE_PATH


def _current_blob_sha() -> str:
    client = get_client()
    user_id = settings.composio_user_id_github or settings.composio_user_id
    res = client.tools.execute(
        T.GITHUB_GET_CONTENT,
        arguments={
            "owner": settings.repo_owner,
            "repo": settings.repo_name,
            "path": DEMO_FILE_PATH,
            "ref": settings.default_branch,
        },
        user_id=user_id,
        dangerously_skip_version_check=True,
    )
    data = res.get("data", res) if isinstance(res, dict) else {}
    return data.get("sha", "") if isinstance(data, dict) else ""


def main() -> None:
    problems = settings.validate()
    if any("REPO" in p or "COMPOSIO" in p for p in problems):
        raise SystemExit("Config incomplete: " + "; ".join(problems))

    blob_sha = _current_blob_sha()
    encoded = base64.b64encode(BROKEN_LOGIC.encode("utf-8")).decode("ascii")
    args = {
        "owner": settings.repo_owner,
        "repo": settings.repo_name,
        "path": DEMO_FILE_PATH,
        "message": "feat: optimise compute (introduces bug)",
        "content": encoded,
        "branch": settings.default_branch,
    }
    if blob_sha:
        args["sha"] = blob_sha

    execute_tool("setup-break", "break_demo", T.GITHUB_UPSERT_FILE, args, retries=1)
    print(f"💥 Broke {settings.repo_full_name()}:{DEMO_FILE_PATH} on '{settings.default_branch}'.")
    print("   CI will go red and /compute will 500. Trigger Sentinel now.")


if __name__ == "__main__":
    main()
