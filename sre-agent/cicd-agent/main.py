"""CI/CD agent — FastAPI wrapper over mock_cicd, with inbound A2A verification."""

from __future__ import annotations

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parent.parent / "shared"
if (_shared / "xtap_identity.py").is_file() and str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

from fastapi import FastAPI, Request
from pydantic import BaseModel
from xtap_fabric_starlette import IncomingTaskMiddleware

from mock_cicd import trigger_deploy
from xtap_identity import AGENT_CICD, enroll_agent, load_dotenv_if_present, require_coordinator_presenter

load_dotenv_if_present()
_agent = enroll_agent(AGENT_CICD)

app = FastAPI(title="cicd-agent", version="0.1.0")
app.add_middleware(
    IncomingTaskMiddleware,
    agent=_agent,
    skip_paths=["/health"],
)


class DeployRequest(BaseModel):
    product: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/deploy")
def deploy(request: Request, req: DeployRequest) -> dict:
    require_coordinator_presenter(request.state.xtap_incoming)
    result = trigger_deploy(req.product)
    return result
