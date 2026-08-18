"""CI/CD agent — plain FastAPI wrapper over mock_cicd."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from mock_cicd import trigger_deploy

app = FastAPI(title="cicd-agent", version="0.1.0")


class DeployRequest(BaseModel):
    product: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/deploy")
def deploy(req: DeployRequest) -> dict:
    result = trigger_deploy(req.product)
    return result
