# SRE Agent — XTap Fabric integration

Multi-service SRE debugging demo. **Each agent is its own process** (Docker Compose by default). Fabric wraps identity, human consent, and task-bound A2A credentials around the existing topology. GitHub / Datadog / CI/CD backends stay in-memory mocks.

## Architecture

```
┌─────────────────┐   A2A hop    ┌───────────────┐
│ sre-coordinator │─────────────▶│ github-agent  │
│  (LangGraph)    │─────────────▶│ datadog-agent │
│                 │─────────────▶│  cicd-agent   │
└─────────────────┘              └───────────────┘
        ▲
   mock Slack poll
   (alert fixture)
```

| Service | Role | LLM? | Fabric role |
|---------|------|------|-------------|
| **sre-coordinator** | Receives alert, reasons, calls other agents | Yes (LangGraph ReAct) | Enrolls, collects consent, `delegate_subtask` + `prepare_a2a_presentation` |
| **github-agent** | Read repo files, commit fixes | No (FastAPI) | Enrolls, `IncomingTaskMiddleware` + sender allowlist |
| **datadog-agent** | Query logs for a service | No (FastAPI) | Same receive-side pattern |
| **cicd-agent** | Trigger deploys | No (FastAPI) | Same receive-side pattern |

Hops are real HTTP across a network boundary between **separately enrolled** ACT agents. That is an A2A presentation (`Authorization: DPoP <task token>`), **not** `SigningHttpClient` / `wrap_signed`. Specialist mocks are in-process; they do not call third-party HTTP.

## Open questions before integrating XTap Fabric into sre-agent

Answered from the repo, with flagged assumptions where the owner still needs to confirm:

1. **Topology** — Four separately deployed processes. Coordinator → github / datadog / cicd are real HTTP hops. In-process LangGraph tool calls are not ACT hops. **Assumption:** all four services enroll with ACT; mocks behind the specialists are pure resources (no identity).
2. **Outbound HTTP** — Coordinator tools call enrolled agents → A2A hop recipe. Specialist handlers call local mocks → no `SigningHttpClient`. OpenAI for the coordinator LLM is left on LangChain (not a Fabric-signed tool).
3. **Task granularity** — One parent ACT task per Slack alert. One **new** child subtask per HTTP hop (no reuse across calls to the same specialist).
4. **Consent placement** — After the mock Slack alert is received, before the graph runs. **Mode A** with `open_browser=False`: copy the printed URL and Approve. In Compose the callback binds `0.0.0.0:9876` and ACT is given `http://127.0.0.1:9876/callback` (published to the host). `consent_via_local_browser` cannot split bind vs redirect host, so this uses `LocalCallbackServer` + `start_consent_par`.
5. **Standing vs per-request** — Independently consented parent authority per Slack message, then `delegate_subtask` per hop. Not standing authority across coordinator restarts (ephemeral DPoP keys are process-lifetime).
6. **`client_id` distribution** — **Assumption:** env vars (`GITHUB_AGENT_CLIENT_ID`, …) with a shared `data/client-ids/` directory as fallback after each process enrolls. `resource=` on `delegate_subtask` is the receiver's ACT `client_id`, never a URL.
7. **Actions** — **Assumption:** parent and children use `["read", "complete"]` as in the SDK eval guide. Commit/deploy are not separate ACT actions here; repo ownership (`payments-lib`) is still application policy.

## Fabric invoke path

```
check_act_health / load_or_enroll_from_env   (once per process)
  → wait for /health + peer client_ids
  → Mode A: print authorize URL → Approve → http://127.0.0.1:9876/callback
  → per HTTP hop: delegate_subtask → prepare_a2a_presentation → httpx
       receiver: IncomingTaskMiddleware → request.state.xtap_incoming
       allowlist immediate_sender == SRE_COORDINATOR_CLIENT_ID
  → LangGraph astream (same tools / prompt as before)
  → complete_task(each child) then complete_task(parent)   # coordinator only
```

## Prerequisites

- Python **3.11+** (Compose images are 3.12)
- Docker and Docker Compose, or four local terminals
- Network access to Cloudsmith and to `XTAP_URL`
- OpenAI API key
- Entitlement token, per-process `SOFTWARE_ID` / `SOFTWARE_SECRET`, and passphrase

Private evaluation: do not republish the wheels or commit the Cloudsmith token.

## Install (local venv)

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install xtap-fabric xtap-fabric-starlette \
  --index-url "https://airaa-airaa:${CLOUDSMITH_TOKEN}@dl.cloudsmith.io/basic/xtap/xtap/python/simple/" \
  --extra-index-url https://pypi.org/simple

python -c "import xtap_fabric; print(xtap_fabric.__version__)"
```

`--extra-index-url` is required so httpx / pydantic / cryptography still come from PyPI.

## Quick start (Compose)

Mode A prints an authorize URL (`open_browser=False`). After Approve, ACT redirects to `http://127.0.0.1:9876/callback`, which Compose publishes from the coordinator container.

1. Copy `.env.example` to `.env` and fill ACT, Cloudsmith, software pairs, and `OPENAI_API_KEY`.

2. Identity dirs are bind-mounted at `./data/<service>` (`XTAP_AGENT_STATE_DIR=/var/lib/xtap`). Do not wipe them between runs or processes re-enroll (new `client_id`s).

3. Start:

   ```bash
   docker compose up --build
   ```

4. When the coordinator prints `Copy this URL into your browser and Approve`, paste it, Approve, and wait for the tab to hit `http://127.0.0.1:9876/callback`.

Set `SCENARIO=complicated` for the payments-lib path.

## Scenarios

| Scenario | Expected behavior |
|----------|-------------------|
| **simple** | Investigation converges on `checkout-service`, commits a fix there |
| **complicated** | Agent may also read (and commit to) `payments-lib` |

The investigation path is **not hardcoded** — the LLM decides which services and repos to query. Fabric authenticates hops; it does not encode repo ownership.

## Running locally (without Docker)

Each specialist maps `GITHUB_AGENT_SOFTWARE_ID` (etc.) onto `XTAP_SOFTWARE_ID` if the latter is unset. Use **localhost URLs** consistently so DPoP `htu` matches (`str(request.url)`).

```bash
# Terminal 1 — github-agent
cd github-agent && pip install -r requirements.txt \
  --index-url "$PIP_INDEX_URL" --extra-index-url https://pypi.org/simple
uvicorn main:app --port 8001

# Terminal 2 — datadog-agent (port 8002)
# Terminal 3 — cicd-agent (port 8003)

# Terminal 4 — sre-coordinator
cd sre-coordinator
export GITHUB_AGENT_URL=http://localhost:8001
export DATADOG_AGENT_URL=http://localhost:8002
export CICD_AGENT_URL=http://localhost:8003
pip install -r requirements.txt \
  --index-url "$PIP_INDEX_URL" --extra-index-url https://pypi.org/simple
python main.py --scenario simple
```

## Service endpoints

| Service | Port | Endpoints |
|---------|------|-----------|
| github-agent | 8001 | `GET /health`, `GET /read`, `GET /list`, `POST /commit` |
| datadog-agent | 8002 | `GET /health`, `POST /query?service=` |
| cicd-agent | 8003 | `GET /health`, `POST /deploy` |

`/health` is unsigned (`IncomingTaskMiddleware` `skip_paths` exact match). Other routes require a valid A2A presentation from the coordinator.
