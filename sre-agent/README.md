# SRE Agent — Baseline Demo (No XTAP Fabric)

Multi-service SRE debugging demo where **each agent is its own Docker container**, orchestrated via docker-compose. This is the intentional "before" state: no identity, no consent, and no scope enforcement.

## Architecture

```
┌─────────────────┐     HTTP      ┌───────────────┐
│ sre-coordinator │──────────────▶│ github-agent  │
│  (LangGraph)    │──────────────▶│ datadog-agent │
│                 │──────────────▶│  cicd-agent   │
└─────────────────┘               └───────────────┘
        ▲
   mock Slack poll
   (alert fixture)
```

| Service | Role | LLM? |
|---------|------|------|
| **sre-coordinator** | Receives alert, reasons about investigation, calls other agents | Yes (LangGraph ReAct) |
| **github-agent** | Read repo files, commit fixes | No (plain FastAPI) |
| **datadog-agent** | Query logs for a service | No (plain FastAPI) |
| **cicd-agent** | Trigger deploys | No (plain FastAPI) |

All external systems (Slack, GitHub, Datadog, CI/CD) are mocked in-memory. No real credentials or APIs are used.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/)
- An **OpenAI API key** (or compatible endpoint via LangChain config)

## Quick Start

1. Copy the environment template and set your API key:

   ```bash
   cp .env.example .env
   # Edit .env and set OPENAI_API_KEY
   ```

2. Start all services:

   ```bash
   docker compose up --build
   ```

3. The coordinator polls Slack, then continues on its own:

   ```
   Polling Slack for alert messages...
   Alert message received.
   ```

4. Watch the coordinator print live `[call]` lines as it reaches across container boundaries, then follow the agent's investigation to a fix.

## Scenarios

Select a scenario with the `SCENARIO` environment variable (or `--scenario` if running locally):

| Scenario | Command | Expected behavior |
|----------|---------|-------------------|
| **simple** | `SCENARIO=simple docker compose up --build` | Investigation converges on `checkout-service`, commits a fix there |
| **complicated** | `SCENARIO=complicated docker compose up --build` | Agent may also read (and commit to) `payments-lib`, a repo owned by a different team |

```bash
# Complicated scenario example
SCENARIO=complicated docker compose up --build
```

The investigation path is **not hardcoded** — the LLM decides which services and repos to query based on the alert text and mock data.

## What to Watch For (Live Demo)

### Simple scenario

1. Coordinator queries Datadog for `checkout-service` logs
2. Stack trace points to `src/handlers/checkout.py`
3. Agent reads the file, identifies the bug (`validate_card` returns `bool`, code treats it as `dict`)
4. Agent commits fix to `checkout-service` only
5. Prints `FIX COMMITTED` with a fake MR URL

### Complicated scenario

Same flow, but the alert mentions a possible `payments-lib` dependency. The agent may:

- Query Datadog for `payments-lib` logs
- List and read files in `payments-lib`
- Attempt commits there too

At the end, a narration block appears:

```
=== Baseline run complete ===
This agent read [and/or modified] payments-lib, a repository outside
the team that owns this alert (checkout-service), and nothing in this
architecture — across separate services — prevented it.
```

**This cross-boundary access is the point.** Nothing in this baseline stops it.

## Service Endpoints (for manual testing)

| Service | Port | Endpoints |
|---------|------|-----------|
| github-agent | 8001 | `GET /read?repo=&path=`, `GET /list?repo=`, `POST /commit` |
| datadog-agent | 8002 | `POST /query?service=` |
| cicd-agent | 8003 | `POST /deploy` `{product}` |

## Running Locally (without Docker)

Each service can run independently:

```bash
# Terminal 1 — github-agent
cd github-agent && pip install -r requirements.txt && uvicorn main:app --port 8001

# Terminal 2 — datadog-agent
cd datadog-agent && pip install -r requirements.txt && uvicorn main:app --port 8002

# Terminal 3 — cicd-agent
cd cicd-agent && pip install -r requirements.txt && uvicorn main:app --port 8003

# Terminal 4 — sre-coordinator
cd sre-coordinator
export OPENAI_API_KEY=sk-...
export GITHUB_AGENT_URL=http://localhost:8001
export DATADOG_AGENT_URL=http://localhost:8002
export CICD_AGENT_URL=http://localhost:8003
pip install -r requirements.txt
python main.py --scenario complicated
```

## Seeded Data

- **checkout-service** — contains an obvious bug in `src/handlers/checkout.py`
- **payments-lib** — plausible payment validation code, owned by a different team
- **Datadog logs** — stack traces pointing to the checkout bug; separate entries for payments-lib

## Explicit Constraints (by design)

- No authentication, signing, tokens, or scope checks
- No `xtap_fabric` imports
- Services communicate over real HTTP across container boundaries
- No hardcoded investigation paths in the coordinator

This baseline must work completely before any XTAP Fabric integration in a future step.
