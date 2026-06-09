"""Composio tool slugs used by Sentinel.

These follow Composio's `TOOLKIT_ACTION` naming. They are centralised here so
that if a slug differs in your Composio account/toolkit version, you change it
in exactly one place.

IMPORTANT: run `python -m scripts.verify_tools` after connecting your accounts.
It lists the actual GitHub/Slack/Linear slugs available to your Composio user
and flags any mismatch with the constants below, so the demo "just works".
"""

# --- GitHub ---------------------------------------------------------------
GITHUB_LIST_COMMITS = "GITHUB_LIST_COMMITS"
GITHUB_GET_COMMIT = "GITHUB_GET_A_COMMIT"
GITHUB_GET_REF = "GITHUB_GET_A_REFERENCE"
GITHUB_CREATE_REF = "GITHUB_CREATE_A_REFERENCE"
GITHUB_GET_CONTENT = "GITHUB_GET_REPOSITORY_CONTENT"
GITHUB_UPSERT_FILE = "GITHUB_CREATE_OR_UPDATE_FILE_CONTENTS"
GITHUB_CREATE_PR = "GITHUB_CREATE_A_PULL_REQUEST"
GITHUB_LIST_CHECK_RUNS = "GITHUB_LIST_CHECK_RUNS_FOR_A_GIT_REFERENCE"
GITHUB_GET_COMBINED_STATUS = "GITHUB_GET_THE_COMBINED_STATUS_FOR_A_SPECIFIC_REFERENCE"
GITHUB_MERGE_PR = "GITHUB_MERGE_A_PULL_REQUEST"

# --- Slack ----------------------------------------------------------------
SLACK_SEND_MESSAGE = "SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL"

# --- Linear ---------------------------------------------------------------
LINEAR_CREATE_ISSUE = "LINEAR_CREATE_LINEAR_ISSUE"

# Toolkits to surface to the LLM in the agentic-loop entry point.
TOOLKITS = ["github", "slack", "linear"]

# Exact slugs the LLM agentic loop is allowed to use (keeps it focused).
AGENTIC_LOOP_TOOLS = [
    GITHUB_LIST_COMMITS,
    GITHUB_GET_COMMIT,
    GITHUB_GET_REF,
    GITHUB_CREATE_REF,
    GITHUB_GET_CONTENT,
    GITHUB_UPSERT_FILE,
    GITHUB_CREATE_PR,
    GITHUB_LIST_CHECK_RUNS,
    GITHUB_GET_COMBINED_STATUS,
    GITHUB_MERGE_PR,
    SLACK_SEND_MESSAGE,
    LINEAR_CREATE_ISSUE,
]
