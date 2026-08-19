"""Datadog agent — FastAPI wrapper over mock_datadog, with inbound A2A verification."""

from __future__ import annotations

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parent.parent / "shared"
if (_shared / "xtap_identity.py").is_file() and str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

from fastapi import FastAPI, Query, Request
from xtap_fabric_starlette import IncomingTaskMiddleware

from mock_datadog import query_logs
from xtap_identity import AGENT_DATADOG, enroll_agent, load_dotenv_if_present, require_coordinator_presenter

load_dotenv_if_present()
_agent = enroll_agent(AGENT_DATADOG)

app = FastAPI(title="datadog-agent", version="0.1.0")
app.add_middleware(
    IncomingTaskMiddleware,
    agent=_agent,
    skip_paths=["/health"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/query")
def query(
    request: Request,
    service: str = Query(..., description="Service name to query logs for"),
) -> dict:
    require_coordinator_presenter(request.state.xtap_incoming)
    logs = query_logs(service)
    return {"service": service, "logs": logs}
