# Sentinel — Autonomous On-Call Agent

The main hackathon submission. Sentinel watches a production service and, when it
breaks, **autonomously reverts the bad commit and merges the fix to `main`** —
then reports to Slack and files a Linear ticket. Composio is the execution layer
for every external action.

> Track 4 (Incident Remediation) · Theme: *Doing over Reasoning*.

## What it does (autonomously, no human in the loop)

1. Receives a Sentry alert at `POST /incident-webhook`.
2. Posts an acknowledgement to Slack.
3. Lists recent commits on the target repo (GitHub, via Composio).
4. **Decides the culprit commit + file** (Claude — the one hard reasoning step).
5. Reverts that file to its last-known-good content on a new branch and opens a PR.
6. Polls GitHub Actions CI until it's green.
7. **Merges the PR** — the autonomous finale. Render redeploys; prod recovers.
8. Writes a postmortem to Slack and files a Linear follow-up ticket.

Every step is traced to SQLite and shown at `/logs` (the Execution Logs deliverable).

## Two execution modes (same Composio execution layer)

| Mode | `TRIGGER_MODE` | What it is | Use when |
|---|---|---|---|
| **Pipeline** (default, recommended) | `pipeline` | Deterministic orchestration; LLM makes the culprit decision + postmortem. Reliable, fast. | Recorded demo / judging. |
| **Agentic** | `agentic` | Claude drives the whole loop, calling Composio tools itself until resolved. | Showing off "fully autonomous agent" behaviour. |

## Architecture

```
Sentry --webhook--> /incident-webhook --> pipeline.run_incident()
                                              │  (all side effects via Composio)
   Slack  <───────────────────────────────────┤  ack / diagnosis / CI / postmortem
   GitHub <───────────────────────────────────┤  list commits, revert file, PR, poll CI, MERGE
   Linear <───────────────────────────────────┘  follow-up ticket
                                              │
                                          tracing (SQLite) --> /logs dashboard
```

Key modules: `agent/pipeline.py` (orchestration), `agent/github_ops.py` (GitHub
primitives), `agent/integrations.py` (Slack/Linear), `agent/llm.py` (reasoning),
`agent/composio_client.py` (traced+retrying Composio wrapper), `agent/server.py`
(HTTP + dashboard).

## Run the offline test (no keys needed)

```bash
cd oncall-agent
pip install -r requirements.txt
pytest -q          # verifies the full pipeline with Composio + LLM mocked
```

## Run locally (live)

```bash
cp .env.example .env      # then fill it in (see operator checklist below)
uvicorn agent.server:app --reload
# open http://127.0.0.1:8000  -> click "Simulate incident"
```

---

## Operator checklist — what YOU provide

The code is complete; these are the human-only setup steps (OAuth/keys can't be
automated). Do them once, in order:

1. **Composio** — sign up, get `COMPOSIO_API_KEY`. Connect **GitHub**, **Slack**,
   and **Linear** for your `COMPOSIO_USER_ID` (default: `default`).
   _(Hackathon: connect Butterbase first — `dashboard.butterbase.ai`, code `HAVEFUN0605`.)_
2. **Anthropic** — get `ANTHROPIC_API_KEY`. Confirm `AGENT_MODEL` matches an
   available model string for your account (default `claude-sonnet-4-6`).
3. **GitHub** — create the `demo-service` repo (push the sibling `demo-service/`
   folder). Set `TARGET_REPO_OWNER` / `TARGET_REPO_NAME`. Ensure Actions are enabled.
4. **Slack** — create an `#incidents` channel; make sure the Composio Slack
   connection can post to it. Set `SLACK_CHANNEL`.
5. **Linear** — get your team id; set `LINEAR_TEAM_ID`.
6. **Deploy demo-service** to Render; set its `SENTRY_DSN`.
7. **Sentry** — create a project, add an issue alert with a webhook action
   pointing at `https://<your-agent>/incident-webhook`.
8. **Deploy this agent** to Render (`render.yaml` included), or run locally and
   expose it (e.g. a tunnel) so Sentry can reach the webhook.
9. **Verify slugs:** `python -m scripts.verify_tools` — confirms the Composio
   tool slugs match your account; fix any in `agent/tool_slugs.py` if flagged.

## Demo runbook (recorded video)

```bash
python -m scripts.reset_demo     # start from green
# (start screen recording; show app /compute healthy, Slack empty, /logs empty)
python -m scripts.break_demo     # commit the bug -> CI red, /compute 500s
# Sentry fires automatically -> Sentinel resolves it. (Backup: click "Simulate incident".)
# Show: Slack messages, the revert PR + merge on GitHub, /compute healthy again, Linear ticket, /logs trace.
python -m scripts.reset_demo     # clean up for the next take
```

The money shot: the moment the revert PR **merges itself** and `/compute` returns 200 again.

## Mandatory requirements → where they're met

- **Composio = execution layer:** all GitHub/Slack/Linear calls go through
  `agent/composio_client.execute_tool` → `composio.tools.execute(...)`.
- **3+ apps:** GitHub + Slack + Linear (+ Sentry trigger).
- **Autonomous final action:** `github_ops.merge_pull_request` runs with no
  human confirmation (`AUTO_MERGE=true`).
- **Execution logs:** `agent/tracing.py` → `/logs`.
