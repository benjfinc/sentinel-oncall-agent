"""Offline end-to-end test of the remediation pipeline.

Verifies the full incident flow — list commits, decide culprit, revert file,
open PR, poll CI, MERGE, postmortem, Linear — with Composio and the LLM mocked.
No API keys required, so CI and `pytest` validate the orchestration logic.

Run from the oncall-agent/ directory:  pytest -q
"""

from __future__ import annotations

import base64
import os
import tempfile

import pytest

from agent import tool_slugs as T


BAD_SHA = "bad0000000000000000000000000000000000000"
GOOD_SHA = "good111111111111111111111111111111111111"


class FakeComposio:
    """Records slug call order and returns canned GitHub/Slack/Linear data."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, incident_id, step, slug, arguments, *, retries=None):
        self.calls.append(slug)
        if slug == T.GITHUB_LIST_COMMITS:
            return [
                {"sha": BAD_SHA, "commit": {"message": "feat: optimise compute (introduces bug)"}},
                {"sha": GOOD_SHA, "commit": {"message": "init service"}},
            ]
        if slug == T.GITHUB_GET_COMMIT:
            # Serves both _commit_files and get_commit_parent.
            return {
                "parents": [{"sha": GOOD_SHA}],
                "files": [{"filename": "app/logic.py"}],
            }
        if slug == T.GITHUB_GET_CONTENT:
            return {
                "content": base64.b64encode(b"return value * 2\n").decode(),
                "sha": "blobsha123",
            }
        if slug == T.GITHUB_GET_REF:
            return {"object": {"sha": "headsha456"}}
        if slug == T.GITHUB_CREATE_REF:
            return {"ref": "refs/heads/sentinel/revert-bad0000"}
        if slug == T.GITHUB_UPSERT_FILE:
            return {"commit": {"sha": "commitsha789"}}
        if slug == T.GITHUB_CREATE_PR:
            return {"number": 42, "html_url": "https://github.com/o/r/pull/42",
                    "head": {"sha": "prheadsha"}}
        if slug == T.GITHUB_GET_COMBINED_STATUS:
            return {"state": "success", "total_count": 1}
        if slug == T.GITHUB_LIST_CHECK_SUITES:
            return {"check_suites": [{"status": "completed", "conclusion": "success"}]}
        if slug == T.GITHUB_MERGE_PR:
            return {"merged": True, "sha": "mergesha"}
        if slug == T.DISCORD_SEND_MESSAGE:
            return {"id": "123456789", "content": arguments.get("content", "")}
        if slug == T.LINEAR_CREATE_ISSUE:
            return {"url": "https://linear.app/team/issue/ABC-1"}
        return {}


@pytest.fixture
def wired(monkeypatch):
    from agent import config, github_ops, integrations, llm, pipeline, tracing

    # Isolated temp trace DB.
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    monkeypatch.setattr(config.settings, "trace_db_path", tmp.name)
    monkeypatch.setattr(tracing.settings, "trace_db_path", tmp.name)
    tracing.init_db()

    # Target repo + fast polling.
    monkeypatch.setattr(config.settings, "repo_owner", "o")
    monkeypatch.setattr(config.settings, "repo_name", "r")
    monkeypatch.setattr(config.settings, "ci_poll_seconds", 0)
    monkeypatch.setattr(config.settings, "auto_merge", True)

    fake = FakeComposio()
    monkeypatch.setattr(github_ops, "execute_tool", fake)
    monkeypatch.setattr(integrations, "execute_tool", fake)

    # Mock the LLM reasoning steps.
    monkeypatch.setattr(
        llm, "decide_culprit",
        lambda commits, et, ed, br: llm.CulpritDecision(
            culprit_sha=BAD_SHA, file_path="app/logic.py",
            confidence=0.95, reasoning="commit touches the failing compute path"),
    )
    monkeypatch.setattr(
        llm, "write_postmortem",
        lambda **kw: "Error: ZeroDivisionError. Reverted bad commit. Resolved.",
    )

    yield fake, pipeline
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def test_full_incident_resolves_and_merges(wired):
    fake, pipeline = wired
    result = pipeline.run_incident(
        "ZeroDivisionError in /compute",
        "GET /compute 500",
        trigger_source="test",
    )

    assert result.status == "resolved"
    assert result.merged is True
    assert result.pr_number == 42
    assert result.culprit_sha == BAD_SHA

    # The autonomous finale must happen, and only after CI is polled.
    assert T.GITHUB_MERGE_PR in fake.calls
    assert fake.calls.index(T.GITHUB_GET_COMBINED_STATUS) < fake.calls.index(T.GITHUB_MERGE_PR)
    # PR is opened before it is merged.
    assert fake.calls.index(T.GITHUB_CREATE_PR) < fake.calls.index(T.GITHUB_MERGE_PR)
    # Discord ack happens before the merge.
    assert fake.calls.index(T.DISCORD_SEND_MESSAGE) < fake.calls.index(T.GITHUB_MERGE_PR)
    # Follow-up ticket filed after resolution.
    assert T.LINEAR_CREATE_ISSUE in fake.calls


def test_ci_failure_blocks_merge(wired, monkeypatch):
    fake, pipeline = wired
    from agent import github_ops
    monkeypatch.setattr(github_ops, "wait_for_ci", lambda incident_id, ref: "failure")
    result = pipeline.run_incident("ZeroDivisionError in /compute", trigger_source="test")

    assert result.status == "failed"
    assert result.merged is False
    assert T.GITHUB_MERGE_PR not in fake.calls
