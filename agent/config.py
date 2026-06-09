"""Central configuration for Sentinel.

Everything that varies between environments (keys, the target repo, the model)
lives here and is read from environment variables. The model is a single swap
point: change AGENT_MODEL to trade speed for reasoning power without touching
any logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv is optional at runtime
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # --- Credentials -------------------------------------------------------
    composio_api_key: str = field(default_factory=lambda: os.getenv("COMPOSIO_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # Composio scopes external connections (GitHub/Slack/Linear) per user_id.
    composio_user_id: str = field(default_factory=lambda: os.getenv("COMPOSIO_USER_ID", "default"))

    # --- Model (single swap point) ----------------------------------------
    # Default to a fast, reliable tool-calling model for snappy demos.
    # Bump to an Opus-class model only if culprit detection needs more power.
    model: str = field(default_factory=lambda: os.getenv("AGENT_MODEL", "claude-sonnet-4-6"))
    # Optional: escalate ONLY the culprit-detection step to a stronger model.
    culprit_model: str = field(default_factory=lambda: os.getenv("CULPRIT_MODEL", ""))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("AGENT_MAX_TOKENS", "4096")))

    # --- Target repo the agent operates on --------------------------------
    repo_owner: str = field(default_factory=lambda: os.getenv("TARGET_REPO_OWNER", ""))
    repo_name: str = field(default_factory=lambda: os.getenv("TARGET_REPO_NAME", ""))
    default_branch: str = field(default_factory=lambda: os.getenv("TARGET_DEFAULT_BRANCH", "main"))
    commit_scan_limit: int = field(default_factory=lambda: int(os.getenv("COMMIT_SCAN_LIMIT", "10")))

    # --- Discord / Linear --------------------------------------------------
    # Discord channel ID (right-click channel in Discord → Copy Channel ID).
    discord_channel_id: str = field(default_factory=lambda: os.getenv("DISCORD_CHANNEL_ID", ""))
    linear_team_id: str = field(default_factory=lambda: os.getenv("LINEAR_TEAM_ID", ""))

    # --- CI polling --------------------------------------------------------
    ci_poll_seconds: int = field(default_factory=lambda: int(os.getenv("CI_POLL_SECONDS", "10")))
    ci_poll_max_attempts: int = field(default_factory=lambda: int(os.getenv("CI_POLL_MAX_ATTEMPTS", "30")))

    # --- Behaviour ---------------------------------------------------------
    # When true, the merge step is the autonomous finale (no confirmation).
    auto_merge: bool = field(default_factory=lambda: _bool("AUTO_MERGE", True))
    tool_retries: int = field(default_factory=lambda: int(os.getenv("TOOL_RETRIES", "1")))

    # --- Storage -----------------------------------------------------------
    trace_db_path: str = field(default_factory=lambda: os.getenv("TRACE_DB_PATH", "sentinel_traces.sqlite"))

    def repo_full_name(self) -> str:
        return f"{self.repo_owner}/{self.repo_name}"

    def validate(self) -> list[str]:
        """Return a list of human-readable problems with the current config."""
        problems: list[str] = []
        if not self.composio_api_key:
            problems.append("COMPOSIO_API_KEY is not set")
        if not self.anthropic_api_key:
            problems.append("ANTHROPIC_API_KEY is not set")
        if not self.repo_owner or not self.repo_name:
            problems.append("TARGET_REPO_OWNER / TARGET_REPO_NAME are not set")
        if not self.discord_channel_id:
            problems.append("DISCORD_CHANNEL_ID is not set")
        if not self.linear_team_id:
            problems.append("LINEAR_TEAM_ID is not set (needed to create follow-up tickets)")
        return problems


settings = Settings()
