"""The remediation pipeline — Sentinel's end-to-end incident response.

This is the primary, reliable path. It is autonomous end to end: an LLM makes
the one hard decision (which commit is the culprit) and writes the postmortem,
while the deterministic orchestration guarantees the steps execute in order via
Composio. Every action is traced for the /logs dashboard.

Sequence:
  1. Acknowledge in Slack.
  2. List recent commits (GitHub).
  3. Decide the culprit commit + file (LLM).
  4. Revert that file to its last-known-good content on a fix branch + open PR.
  5. Poll CI until green.
  6. Merge the PR — the autonomous finale (no human in the loop).
  7. Post a postmortem to Slack.
  8. File a Linear follow-up ticket.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from . import github_ops as gh
from . import integrations, llm, tracing
from .config import settings


@dataclass
class IncidentResult:
    incident_id: str
    status: str
    culprit_sha: str = ""
    file_path: str = ""
    pr_number: int = 0
    pr_url: str = ""
    ci_result: str = ""
    merged: bool = False
    summary: str = ""


def _fix_branch_name(culprit_sha: str) -> str:
    return f"sentinel/revert-{culprit_sha[:7]}-{int(time.time())}"


def run_incident(
    error_title: str,
    error_detail: str = "",
    trigger_source: str = "manual",
) -> IncidentResult:
    """Run the full remediation flow for one incident. Never raises; failures
    are recorded and returned in the result so the server can respond cleanly."""
    incident_id = tracing.start_incident(trigger_source, error_title)
    started = time.time()
    branch = settings.default_branch
    result = IncidentResult(incident_id=incident_id, status="running")

    try:
        # 1. Acknowledge ---------------------------------------------------
        integrations.slack_post(
            incident_id,
            "ack",
            f":rotating_light: *Sentinel*: detected production errors "
            f"(`{error_title}`) on `{settings.repo_full_name()}`. Investigating…",
        )

        # 2. List commits --------------------------------------------------
        commits = gh.list_recent_commits(incident_id)
        if not commits:
            raise RuntimeError("no recent commits found to analyse")

        # 3. Decide the culprit (LLM) -------------------------------------
        decision = llm.decide_culprit(commits, error_title, error_detail, branch)
        tracing.log_event(
            incident_id,
            "decide_culprit",
            "decision",
            request={"error": error_title, "commits": commits},
            response=asdict(decision),
            ok=True,
            note=f"confidence={decision.confidence}",
        )
        result.culprit_sha = decision.culprit_sha
        result.file_path = decision.file_path

        culprit_message = next(
            (c["message"].splitlines()[0] for c in commits
             if c["sha"].startswith(decision.culprit_sha[:7]) and c["message"]),
            "",
        )

        integrations.slack_post(
            incident_id,
            "diagnosis",
            f":mag: Likely cause: commit `{decision.culprit_sha[:7]}` "
            f"touching `{decision.file_path}`.\n> {decision.reasoning}\n"
            f"Preparing a revert PR…",
        )

        # 4. Revert the file + open PR ------------------------------------
        parent_sha = gh.get_commit_parent(incident_id, decision.culprit_sha)
        if not parent_sha:
            raise RuntimeError(f"could not find parent of {decision.culprit_sha}")

        good_text, _ = gh.get_file(incident_id, decision.file_path, ref=parent_sha)
        if not good_text:
            raise RuntimeError(
                f"could not read known-good content of {decision.file_path} at {parent_sha[:7]}"
            )

        head_sha = gh.get_branch_head(incident_id, branch)
        fix_branch = _fix_branch_name(decision.culprit_sha)
        gh.create_branch(incident_id, fix_branch, head_sha)

        _, current_blob_sha = gh.get_file(incident_id, decision.file_path, ref=branch)
        gh.commit_file(
            incident_id,
            decision.file_path,
            good_text,
            fix_branch,
            current_blob_sha,
            message=f"Revert {decision.culprit_sha[:7]}: restore {decision.file_path}",
        )

        pr = gh.create_pull_request(
            incident_id,
            head=fix_branch,
            base=branch,
            title=f"[Sentinel] Auto-revert {decision.culprit_sha[:7]} to restore prod",
            body=(
                f"Automated revert opened by **Sentinel** in response to a production incident.\n\n"
                f"- **Error:** {error_title}\n"
                f"- **Culprit commit:** {decision.culprit_sha}\n"
                f"- **Reverted file:** `{decision.file_path}`\n"
                f"- **Reasoning:** {decision.reasoning}\n\n"
                f"Merging once CI is green."
            ),
        )
        result.pr_number = int(pr.get("number") or 0)
        result.pr_url = pr.get("html_url", "")

        # 5. Poll CI -------------------------------------------------------
        ci_ref = pr.get("head_sha") or fix_branch
        ci_result = gh.wait_for_ci(incident_id, ci_ref)
        result.ci_result = ci_result
        integrations.slack_post(
            incident_id,
            "ci_status",
            f":test_tube: CI on revert PR #{result.pr_number}: *{ci_result}*.",
        )
        if ci_result != "success":
            raise RuntimeError(f"CI did not pass (result={ci_result}); not merging")

        # 6. Merge — the autonomous finale --------------------------------
        if not settings.auto_merge:
            result.status = "awaiting_merge"
            result.summary = "CI green; auto-merge disabled, awaiting human."
            tracing.finish_incident(incident_id, result.status, result.summary)
            return result

        merge = gh.merge_pull_request(incident_id, result.pr_number)
        result.merged = bool(merge.get("merged"))

        duration = f"{time.time() - started:.0f}s"

        # 7. Postmortem to Slack ------------------------------------------
        postmortem = llm.write_postmortem(
            error_title=error_title,
            culprit_sha=decision.culprit_sha,
            culprit_message=culprit_message,
            pr_number=result.pr_number,
            pr_url=result.pr_url,
            file_path=decision.file_path,
            branch=branch,
            duration=duration,
        )
        integrations.slack_post(incident_id, "postmortem", f":white_check_mark: *Resolved*\n{postmortem}")

        # 8. Linear follow-up ---------------------------------------------
        linear = integrations.linear_create_issue(
            incident_id,
            title=f"[Postmortem] {error_title} — auto-reverted by Sentinel",
            description=(
                f"Sentinel auto-resolved a production incident.\n\n"
                f"- Culprit: {decision.culprit_sha} ({culprit_message})\n"
                f"- Reverted file: {decision.file_path}\n"
                f"- PR: {result.pr_url}\n"
                f"- Resolution time: {duration}\n\n"
                f"Please review the root cause and confirm the revert is the right long-term fix."
            ),
        )
        tracing.log_event(
            incident_id, "linear_followup", "info",
            response={"url": linear.get("url")}, ok=True,
        )

        result.status = "resolved"
        result.summary = (
            f"Reverted {decision.culprit_sha[:7]} via PR #{result.pr_number}, "
            f"merged in {duration}."
        )
        tracing.finish_incident(incident_id, result.status, result.summary)
        return result

    except Exception as exc:  # noqa: BLE001 — we want to record any failure
        result.status = "failed"
        result.summary = str(exc)
        tracing.log_event(incident_id, "pipeline", "error", response=str(exc), ok=False)
        try:
            integrations.slack_post(
                incident_id,
                "failure",
                f":warning: Sentinel could not auto-resolve `{error_title}`: {exc}. "
                f"Escalating to a human.",
            )
        except Exception:
            pass
        tracing.finish_incident(incident_id, result.status, result.summary)
        return result


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
