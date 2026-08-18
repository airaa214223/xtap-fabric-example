"""Datadog agent — FastAPI mock with XTap Fabric enroll + accept_incoming_task."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query

from mock_datadog import query_logs
from xtap_runtime import enroll_this_agent, health_payload, install_accept_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.xtap_agent = await enroll_this_agent(
        "datadog-agent",
        "Datadog Agent",
        "Mock Datadog log query service for the SRE demo",
    )
    yield


app = FastAPI(title="datadog-agent", version="0.1.0", lifespan=lifespan)
install_accept_middleware(app)


@app.get("/health")
def health() -> dict[str, str]:
    return health_payload()


@app.post("/query")
def query(service: str = Query(..., description="Service name to query logs for")) -> dict:
    logs = query_logs(service)
    return {"service": service, "logs": logs}
