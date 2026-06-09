"""GitHub remediation primitives, each backed by a Composio tool call.

These wrap the raw Composio GitHub tools into intention-revealing functions the
pipeline composes: list commits, read a file at a ref, branch, revert a file,
open a PR, poll CI, merge. All side effects go through `composio_client.execute_tool`
so they are traced and retried uniformly.

Response parsing is defensive: Composio mirrors the GitHub REST API but the exact
envelope can vary by toolkit version, so we look in a few likely places.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from . import tool_slugs as T
from .composio_client import execute_tool
from .config import settings


def _dig(obj: Any, *keys: str, default: Any = None) -> Any:
    """Walk nested dict keys, tolerating a 'data'/'response_data' wrapper."""
    for candidate in (obj, obj.get("data") if isinstance(obj, dict) else None,
                       obj.get("response_data") if isinstance(obj, dict) else None):
        cur = candidate
        ok = True
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default


def _owner_repo() -> dict:
    return {"owner": settings.repo_owner, "repo": settings.repo_name}


def list_recent_commits(incident_id: str) -> list[dict]:
    """Return recent commits on the default branch with their changed files.

    Each item: {sha, message, files: [path, ...]}.
    """
    raw = execute_tool(
        incident_id,
        "list_commits",
        T.GITHUB_LIST_COMMITS,
        {**_owner_repo(), "sha": settings.default_branch, "per_page": settings.commit_scan_limit},
    )
    items = raw if isinstance(raw, list) else _dig(raw, "commits", default=raw)
    if isinstance(items, dict):
        items = items.get("items") or items.get("data") or []

    commits: list[dict] = []
    for item in (items or [])[: settings.commit_scan_limit]:
        sha = item.get("sha") if isinstance(item, dict) else None
        message = _dig(item, "commit", "message", default="") if isinstance(item, dict) else ""
        if not sha:
            continue
        files = _commit_files(incident_id, sha)
        commits.append({"sha": sha, "message": message, "files": files})
    return commits


def _commit_files(incident_id: str, sha: str) -> list[str]:
    raw = execute_tool(
        incident_id,
        "get_commit",
        T.GITHUB_GET_COMMIT,
        {**_owner_repo(), "ref": sha},
    )
    files = _dig(raw, "files", default=[]) or []
    paths = []
    for f in files:
        if isinstance(f, dict) and f.get("filename"):
            paths.append(f["filename"])
    return paths


def get_commit_parent(incident_id: str, sha: str) -> str:
    raw = execute_tool(
        incident_id,
        "get_commit_parent",
        T.GITHUB_GET_COMMIT,
        {**_owner_repo(), "ref": sha},
    )
    parents = _dig(raw, "parents", default=[]) or []
    if parents and isinstance(parents[0], dict):
        return parents[0].get("sha", "")
    return ""


def get_file(incident_id: str, path: str, ref: str) -> tuple[str, str]:
    """Return (decoded_text, blob_sha) for a file at a given ref.

    Composio wraps GitHub's file response as:
      { data: { content: { content: "<base64>", sha: "...", ... } } }
    We try multiple nesting levels to be resilient to version changes.
    """
    raw = execute_tool(
        incident_id,
        "get_content",
        T.GITHUB_GET_CONTENT,
        {**_owner_repo(), "path": path, "ref": ref},
    )
    # Try nested: data -> content -> content (Composio v1.0 shape)
    file_obj = None
    if isinstance(raw, dict):
        data = raw.get("data", raw)
        if isinstance(data, dict):
            inner = data.get("content", data)
            if isinstance(inner, dict) and "content" in inner:
                file_obj = inner           # { content: b64, sha: ..., ... }
            elif isinstance(inner, str):
                file_obj = data            # data itself has content string
            else:
                file_obj = data

    content_b64 = ""
    blob_sha = ""
    if isinstance(file_obj, dict):
        content_b64 = file_obj.get("content", "")
        blob_sha = file_obj.get("sha", "")

    text = ""
    if content_b64 and isinstance(content_b64, str):
        try:
            # GitHub embeds newlines in base64 — strip them before decoding
            text = base64.b64decode(content_b64.replace("\n", "")).decode("utf-8")
        except Exception:
            text = ""
    return text, blob_sha


def get_branch_head(incident_id: str, branch: str) -> str:
    raw = execute_tool(
        incident_id,
        "get_ref",
        T.GITHUB_GET_REF,
        {**_owner_repo(), "ref": f"heads/{branch}"},
    )
    return _dig(raw, "object", "sha", default="") or _dig(raw, "sha", default="")


def create_branch(incident_id: str, new_branch: str, from_sha: str) -> None:
    execute_tool(
        incident_id,
        "create_branch",
        T.GITHUB_CREATE_REF,
        {**_owner_repo(), "ref": f"refs/heads/{new_branch}", "sha": from_sha},
    )


def commit_file(
    incident_id: str,
    path: str,
    content_text: str,
    branch: str,
    blob_sha: str,
    message: str,
) -> None:
    """Create/update a file on a branch (used to write the reverted content)."""
    encoded = base64.b64encode(content_text.encode("utf-8")).decode("ascii")
    args = {
        **_owner_repo(),
        "path": path,
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if blob_sha:
        args["sha"] = blob_sha
    execute_tool(incident_id, "commit_revert", T.GITHUB_UPSERT_FILE, args)


def create_pull_request(
    incident_id: str, head: str, base: str, title: str, body: str
) -> dict:
    """Open a PR. Returns {number, html_url, head_sha}."""
    raw = execute_tool(
        incident_id,
        "create_pr",
        T.GITHUB_CREATE_PR,
        {**_owner_repo(), "head": head, "base": base, "title": title, "body": body},
    )
    return {
        "number": _dig(raw, "number", default=0),
        "html_url": _dig(raw, "html_url", default=""),
        "head_sha": _dig(raw, "head", "sha", default=""),
    }


def wait_for_ci(incident_id: str, ref: str) -> str:
    """Poll CI for `ref` until it concludes. Returns 'success'|'failure'|'timeout'.

    GitHub Actions does NOT set commit statuses — it uses check suites.  We
    therefore query check suites directly and look only at the suite belonging
    to the 'GitHub Actions' app.  Third-party suites (Cursor, Vercel, etc.)
    are ignored because they may never transition out of 'queued'.
    """
    for attempt in range(1, settings.ci_poll_max_attempts + 1):
        # Primary path: check suites filtered to GitHub Actions
        suite_raw = execute_tool(
            incident_id,
            "poll_ci_suites",
            T.GITHUB_LIST_CHECK_SUITES,
            {**_owner_repo(), "ref": ref},
        )
        suites = _dig(suite_raw, "check_suites", default=[]) or []
        if isinstance(suites, list) and suites:
            actions_suites = [
                s for s in suites
                if isinstance(s, dict)
                and isinstance(s.get("app"), dict)
                and "GitHub Actions" in s["app"].get("name", "")
            ]
            if actions_suites:
                # All GitHub Actions suites completed → decide
                all_done = all(s.get("status") == "completed" for s in actions_suites)
                if all_done:
                    if all(s.get("conclusion") == "success" for s in actions_suites):
                        return "success"
                    return "failure"
                # At least one not done yet — keep polling

        # Fallback: combined commit status (older repos / non-Actions CI)
        cs_raw = execute_tool(
            incident_id,
            "poll_ci",
            T.GITHUB_GET_COMBINED_STATUS,
            {**_owner_repo(), "ref": ref},
        )
        state = _dig(cs_raw, "state", default="pending") or "pending"
        if state == "success":
            return "success"
        if state in {"failure", "error"}:
            return "failure"

        time.sleep(settings.ci_poll_seconds)
    return "timeout"


def merge_pull_request(incident_id: str, number: int) -> dict:
    """THE autonomous finale: merge the revert PR to recover prod."""
    raw = execute_tool(
        incident_id,
        "merge_pr",
        T.GITHUB_MERGE_PR,
        {
            **_owner_repo(),
            "pull_number": number,
            "merge_method": "squash",
            "commit_title": f"Sentinel: auto-revert via PR #{number}",
        },
    )
    return {"merged": bool(_dig(raw, "merged", default=True)), "sha": _dig(raw, "sha", default="")}
