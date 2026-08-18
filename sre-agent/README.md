# SRE Agent — Fabric identity, consent, and signed hops

Multi-service SRE debugging demo. Each agent is its own Docker container and **enrolls separately** against ACT. The coordinator gets human consent (Mode A), then each tool call is an ACT hop plus signed HTTP. Transport is still plain HTTP to github/datadog/cicd — Fabric does not send those requests for you.

## Architecture

```
┌─────────────────┐  delegate_subtask + SigningHttpClient   ┌───────────────┐
│ sre-coordinator │────────────────────────────────────────▶│ github-agent  │
│  LangGraph      │────────────────────────────────────────▶│ datadog-agent │
│  Mode A consent │────────────────────────────────────────▶│  cicd-agent   │
└─────────────────┘                                          └───────────────┘
        ▲  print authorize URL (port 8765)
   mock Slack poll
```

| Service | Role | LLM? | Fabric |
|---------|------|------|--------|
| **sre-coordinator** | Reasons about the alert, calls specialists | Yes | enroll, consent, wrap_signed, delegate_subtask, complete_task |
| **github-agent** | Read/commit mock repos | No | enroll, accept_incoming_task |
| **datadog-agent** | Query mock logs | No | enroll, accept_incoming_task |
| **cicd-agent** | Trigger mock deploys | No | enroll, accept_incoming_task |

## Prerequisites

- Docker / Docker Compose
- Python 3.11+ (for local runs)
- OpenAI API key
- ACT: `XTAP_URL`, `XTAP_TENANT_ID`, `XTAP_KEY_PASSPHRASE`
- **One software id + secret per agent** (four pairs)
- Cloudsmith entitlement to install `xtap-fabric` (and `xtap-fabric-langchain` on the coordinator)
- A real browser (consent is a human Approve)

## Install the private packages

```bash
pip install xtap-fabric 'xtap-fabric-langchain[langchain]' \
  --index-url "https://dl.cloudsmith.io/${CLOUDSMITH_TOKEN}/${CLOUDSMITH_OWNER}/${CLOUDSMITH_REPO}/python/simple/" \
  --extra-index-url https://pypi.org/simple
```

For Docker, put the same index URL in `.env` as `PIP_INDEX_URL`.

## Environment

```bash
cp .env.example .env
# Fill OPENAI_API_KEY, XTAP_*, and each agent's SOFTWARE_ID / SOFTWARE_SECRET
```

| Variable | Used by |
|----------|---------|
| `XTAP_URL` | All four services |
| `XTAP_TENANT_ID` | All four (one tenant) |
| `XTAP_KEY_PASSPHRASE` | All four |
| `SRE_COORDINATOR_SOFTWARE_ID` / `_SECRET` | coordinator → `XTAP_SOFTWARE_ID` |
| `GITHUB_AGENT_SOFTWARE_ID` / `_SECRET` | github-agent |
| `DATADOG_AGENT_SOFTWARE_ID` / `_SECRET` | datadog-agent |
| `CICD_AGENT_SOFTWARE_ID` / `_SECRET` | cicd-agent |

Compose maps each pair onto `XTAP_SOFTWARE_ID` / `XTAP_SOFTWARE_SECRET` inside that container so `AgentConfig.from_env()` works.

## Quick start

```bash
docker compose up --build
```

Watch for:

1. Each service: `Checking ACT health...` then `Enrolled <agent-id> client_id=...`
2. `Polling Slack for alert messages...` / `Alert message received.`
3. `Open and Approve: https://...` — open that URL in a browser and Approve
4. `[fabric] delegate_subtask -> ...` then `[call] GET/POST ...`
5. `Fabric task completed.`

Consent callback is `http://127.0.0.1:8765/callback` (published as `8765:8765`). If Approve hangs after you click it, the helper may be bound to container-loopback only; run the coordinator on the host in that case.

## Scenarios

```bash
SCENARIO=simple docker compose up --build
SCENARIO=complicated docker compose up --build
```

The investigation path is still LLM-driven. Fabric records identity and hops; it does **not** block `payments-lib`.

## Runtime path

```text
check_act_health_async
AgentConfig.from_env
Agent.load_or_enroll_async          # each process, own software id
poll Slack
consent_via_local_browser_async     # open_browser=False, print URL, port 8765
wrap_signed                         # coordinator tools
per tool: delegate_subtask → SigningHttpClient HTTP → accept_incoming_task
complete_task_async
```

## Local run (without Docker)

Install `xtap-fabric` into each venv. Export `XTAP_URL`, `XTAP_TENANT_ID`, `XTAP_KEY_PASSPHRASE`, and that service’s `XTAP_SOFTWARE_ID` / `XTAP_SOFTWARE_SECRET`. Point coordinator URLs at `localhost:8001/8002/8003`. Consent still prints a URL on port 8765.
