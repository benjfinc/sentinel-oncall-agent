"""Find connected account user IDs and Linear team UUID."""
from agent.composio_client import get_client
from agent.config import settings
import json

client = get_client()

print("=== Connected accounts ===")
try:
    accounts = client.connected_accounts.list()
    for a in (accounts or []):
        d = a if isinstance(a, dict) else (a.__dict__ if hasattr(a, "__dict__") else {})
        print(" ", json.dumps(d, default=str)[:400])
except Exception as e:
    print(f"Error: {e}")

print("\n=== Linear teams (to find UUID) ===")
try:
    result = client.tools.execute(
        "LINEAR_GET_ALL_LINEAR_TEAMS",
        arguments={},
        user_id=settings.composio_user_id,
        dangerously_skip_version_check=True,
    )
    print(json.dumps(result, default=str)[:1000])
except Exception as e:
    print(f"Error: {e}")
