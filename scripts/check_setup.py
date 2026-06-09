"""Pre-flight check — run this before your live demo.

    python -m scripts.check_setup

Tests every connection Sentinel needs and prints a clear pass/fail for each.
Fix anything that fails before recording. Takes ~10 seconds.
"""

from __future__ import annotations
import sys, os

OK = "\033[92m  ✓\033[0m"
FAIL = "\033[91m  ✗\033[0m"
WARN = "\033[93m  !\033[0m"

errors: list[str] = []

def check(label: str, fn) -> bool:
    try:
        msg = fn()
        print(f"{OK} {label}" + (f" — {msg}" if msg else ""))
        return True
    except Exception as e:
        print(f"{FAIL} {label} — {e}")
        errors.append(label)
        return False


# 1. Config
def _config():
    from agent.config import settings
    problems = settings.validate()
    if problems:
        raise RuntimeError("; ".join(problems))
    return f"repo={settings.repo_full_name()}, model={settings.model}"

# 2. Anthropic reachability
def _anthropic():
    import anthropic
    from agent.config import settings
    c = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    r = c.messages.create(
        model=settings.model, max_tokens=10,
        messages=[{"role": "user", "content": "ping"}]
    )
    return f"model={settings.model} reachable"

# 3. Composio + GitHub: list commits
def _github():
    from agent.config import settings
    from agent.composio_client import execute_tool
    from agent import tool_slugs as T
    commits = execute_tool(
        "check", "check_github", T.GITHUB_LIST_COMMITS,
        {"owner": settings.repo_owner, "repo": settings.repo_name,
         "sha": settings.default_branch, "per_page": 1}
    )
    count = len(commits) if isinstance(commits, list) else "?"
    return f"repo accessible, got {count} commit(s)"

# 4. Composio + Discord: verify channel accessible
def _discord():
    from agent.config import settings
    from agent.composio_client import execute_tool
    from agent import tool_slugs as T
    execute_tool(
        "check", "check_discord", T.DISCORD_SEND_MESSAGE,
        {"channel_id": settings.discord_channel_id,
         "content": "✅ Sentinel pre-flight check — Discord connection OK."}
    )
    return f"posted to channel {settings.discord_channel_id}"

# 5. Composio + Linear: team accessible
def _linear():
    from agent.config import settings
    from agent.composio_client import execute_tool
    from agent import tool_slugs as T
    execute_tool(
        "check", "check_linear", T.LINEAR_CREATE_ISSUE,
        {"team_id": settings.linear_team_id,
         "title": "[Sentinel pre-flight check — delete me]",
         "description": "Pre-flight connectivity test. Please delete."}
    )
    return f"team_id={settings.linear_team_id} accessible"

# 6. GitHub CI: check the demo-service repo has Actions enabled
def _ci():
    from agent.config import settings
    from agent.composio_client import execute_tool
    from agent import tool_slugs as T
    raw = execute_tool(
        "check", "check_ci", T.GITHUB_LIST_CHECK_SUITES,
        {"owner": settings.repo_owner, "repo": settings.repo_name,
         "ref": settings.default_branch}
    )
    suites = raw.get("check_suites", []) if isinstance(raw, dict) else raw or []
    return f"Actions reachable, {len(suites)} check suite(s) on HEAD"


print("\n=== Sentinel pre-flight check ===\n")
check("Config (.env)", _config)
check("Anthropic API (model reachable)", _anthropic)
check("Composio → GitHub (list commits)", _github)
check("Composio → Discord (post message)", _discord)
check("Composio → Linear (create issue)", _linear)
check("GitHub Actions (CI reachable)", _ci)

print()
if errors:
    print(f"\033[91mFailed: {', '.join(errors)}\033[0m")
    print("Fix the above before running the demo.\n")
    sys.exit(1)
else:
    print("\033[92mAll checks passed — you're ready to record.\033[0m\n")
