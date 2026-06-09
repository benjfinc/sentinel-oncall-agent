"""Debug CI status for open PRs."""
import sys
sys.path.insert(0, ".")
from agent.composio_client import get_client
from agent.config import settings

client = get_client()
uid = settings.composio_user_id_github or settings.composio_user_id

# List open PRs
r = client.tools.execute(
    "GITHUB_LIST_PULL_REQUESTS",
    arguments={"owner": "benjfinc", "repo": "demo-service", "state": "open"},
    user_id=uid,
    dangerously_skip_version_check=True,
)
data = r.get("data", r) if isinstance(r, dict) else r
prs = data.get("pull_requests", data.get("items", data)) if isinstance(data, dict) else data
if isinstance(data, list):
    prs = data
print("OPEN PRs:", type(prs))
for pr in (prs if isinstance(prs, list) else [])[:5]:
    if not isinstance(pr, dict):
        continue
    num = pr.get("number")
    title = pr.get("title", "")
    head = pr.get("head", {})
    sha = head.get("sha", "") if isinstance(head, dict) else ""
    print(f"  PR#{num} head={sha[:7]} {title}")

    if not sha:
        continue

    # Check combined status
    cs = client.tools.execute(
        "GITHUB_GET_THE_COMBINED_STATUS_FOR_A_SPECIFIC_REFERENCE",
        arguments={"owner": "benjfinc", "repo": "demo-service", "ref": sha},
        user_id=uid,
        dangerously_skip_version_check=True,
    )
    cs_data = cs.get("data", cs) if isinstance(cs, dict) else cs
    print(f"    combined_status keys: {list(cs_data.keys()) if isinstance(cs_data, dict) else type(cs_data)}")
    if isinstance(cs_data, dict):
        state = cs_data.get("state", "?")
        statuses = cs_data.get("statuses", [])
        print(f"    combined state={state}, statuses count={len(statuses) if isinstance(statuses, list) else statuses}")

    # Check check suites
    suites = client.tools.execute(
        "GITHUB_LIST_CHECK_SUITES_FOR_A_GIT_REFERENCE",
        arguments={"owner": "benjfinc", "repo": "demo-service", "ref": sha},
        user_id=uid,
        dangerously_skip_version_check=True,
    )
    s_data = suites.get("data", suites) if isinstance(suites, dict) else suites
    print(f"    check_suites keys: {list(s_data.keys()) if isinstance(s_data, dict) else type(s_data)}")
    cs_list = s_data.get("check_suites", s_data.get("items", [])) if isinstance(s_data, dict) else []
    if isinstance(cs_list, list):
        for suite in cs_list[:3]:
            if isinstance(suite, dict):
                print(f"      suite status={suite.get('status')} conclusion={suite.get('conclusion')} app={suite.get('app', {}).get('name', '?') if isinstance(suite.get('app'), dict) else '?'}")
