"""Datadog agent — plain FastAPI wrapper over mock_datadog."""

from __future__ import annotations

from fastapi import FastAPI, Query

from mock_datadog import query_logs

app = FastAPI(title="datadog-agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/query")
def query(service: str = Query(..., description="Service name to query logs for")) -> dict:
    logs = query_logs(service)
    return {"service": service, "logs": logs}
