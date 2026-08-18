"""CI/CD agent — FastAPI mock with XTap Fabric enroll + accept_incoming_task."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from mock_cicd import trigger_deploy
from xtap_runtime import enroll_this_agent, health_payload, install_accept_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.xtap_agent = await enroll_this_agent(
        "cicd-agent",
        "CI/CD Agent",
        "Mock CI/CD deploy service for the SRE demo",
    )
    yield


app = FastAPI(title="cicd-agent", version="0.1.0", lifespan=lifespan)
install_accept_middleware(app)


class DeployRequest(BaseModel):
    product: str


@app.get("/health")
def health() -> dict[str, str]:
    return health_payload()


@app.post("/deploy")
def deploy(req: DeployRequest) -> dict:
    result = trigger_deploy(req.product)
    return result
