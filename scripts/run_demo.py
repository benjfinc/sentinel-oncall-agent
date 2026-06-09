"""One-command demo runner — use this when recording the video.

    python -m scripts.run_demo

Sequence:
  1. Resets repo to healthy (clean start).
  2. Breaks the app (commits the staged bug to main).
  3. Triggers Sentinel via /simulate-incident (deterministic, no Sentry flake risk).
  4. Streams the incident trace to your terminal in real time.
  5. Exits 0 when Sentinel resolves the incident (status=resolved).
  6. Prints a summary so you can show it on camera.

All steps print timestamps so you know exactly when to switch windows.
"""

from __future__ import annotations
import sys, time, json, textwrap, subprocess, os
from datetime import datetime

SENTINEL_URL = os.getenv("SENTINEL_URL", "http://127.0.0.1:8000")


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def separator(label: str) -> None:
    width = 60
    print(f"\n{'─' * width}")
    print(f"  {ts()}  {label}")
    print(f"{'─' * width}")


def run(label: str, *args, **kwargs) -> None:
    separator(label)
    result = subprocess.run(list(args), **kwargs)
    if result.returncode != 0:
        print(f"\033[91mFailed (exit {result.returncode})\033[0m")
        sys.exit(result.returncode)


def main() -> None:
    python = sys.executable

    # --- Reset -----------------------------------------------------------
    separator("STEP 1 / 5  Reset demo-service to healthy")
    r = subprocess.run([python, "-m", "scripts.reset_demo"], capture_output=False)
    if r.returncode != 0:
        print("reset_demo failed — is your .env set up? Run check_setup first.")
        sys.exit(1)

    time.sleep(2)   # let Render pick up the push (or local server settle)

    # --- Break -----------------------------------------------------------
    separator("STEP 2 / 5  Break demo-service (commit the staged bug)")
    r = subprocess.run([python, "-m", "scripts.break_demo"], capture_output=False)
    if r.returncode != 0:
        print("break_demo failed — check GitHub connection.")
        sys.exit(1)

    print("\n  The bad commit is now on main. CI will go red.")
    print("  (In a live Sentry setup this auto-triggers Sentinel.)")
    time.sleep(3)

    # --- Trigger Sentinel ------------------------------------------------
    separator("STEP 3 / 5  Trigger Sentinel (simulate-incident)")
    try:
        import urllib.request, urllib.error
        req = urllib.request.Request(
            f"{SENTINEL_URL}/simulate-incident",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            print(f"  Accepted: {body.get('error_title')}")
            incident_hint = None
    except Exception as e:
        print(f"\033[91m  Could not reach Sentinel at {SENTINEL_URL}: {e}\033[0m")
        print("  Is the server running? Start with:  uvicorn agent.server:app")
        sys.exit(1)

    # --- Poll for resolution ---------------------------------------------
    separator("STEP 4 / 5  Watching Sentinel work…")
    print(f"  Live trace: {SENTINEL_URL}/logs\n")

    deadline = time.time() + 300   # 5-minute max
    last_count = 0

    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{SENTINEL_URL}/api/incidents")
            with urllib.request.urlopen(req, timeout=5) as resp:
                incidents = json.loads(resp.read())
            if incidents:
                inc = incidents[0]  # most recent
                status = inc.get("status", "")
                summary = inc.get("summary", "")
                event_hint = f"  [{ts()}] status={status}  {summary[:60]}"
                if event_hint != last_count:
                    print(event_hint)
                    last_count = event_hint
                if status == "resolved":
                    break
                if status == "failed":
                    print(f"\033[91m  Sentinel failed: {summary}\033[0m")
                    sys.exit(1)
        except Exception:
            pass
        time.sleep(5)
    else:
        print("\033[91m  Timed out waiting for resolution.\033[0m")
        sys.exit(1)

    # --- Summary ---------------------------------------------------------
    separator("STEP 5 / 5  Resolved!")
    inc = incidents[0]
    summary = textwrap.fill(inc.get("summary", ""), width=56, initial_indent="  ", subsequent_indent="  ")
    print(f"\n  Incident ID : {inc['id']}")
    print(f"  Status      : \033[92m{inc['status']}\033[0m")
    print(f"  Summary     : {summary}")
    print(f"\n  Execution trace : {SENTINEL_URL}/logs/{inc['id']}")
    print(f"\n\033[92m  Sentinel fixed prod autonomously. Recording complete.\033[0m\n")


if __name__ == "__main__":
    main()
