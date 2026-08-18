"""GitHub agent — FastAPI mock with XTap Fabric enroll + accept_incoming_task."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from mock_github import commit_and_push, list_files, read_repo
from xtap_runtime import enroll_this_agent, health_payload, install_accept_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.xtap_agent = await enroll_this_agent(
        "github-agent",
        "GitHub Agent",
        "Mock GitHub read/commit service for the SRE demo",
    )
    yield


app = FastAPI(title="github-agent", version="0.1.0", lifespan=lifespan)
install_accept_middleware(app)


class CommitRequest(BaseModel):
    repo: str
    diff: str


@app.get("/health")
def health() -> dict[str, str]:
    return health_payload()


@app.get("/read")
def read_file(
    repo: str = Query(..., description="Repository name"),
    path: str = Query(..., description="File path within the repo"),
) -> dict[str, str]:
    try:
        content = read_repo(repo, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"repo": repo, "path": path, "content": content}


@app.get("/list")
def list_repo_files(repo: str = Query(..., description="Repository name")) -> dict:
    try:
        files = list_files(repo)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"repo": repo, "files": files}


@app.post("/commit")
def commit(req: CommitRequest) -> dict:
    try:
        result = commit_and_push(req.repo, req.diff)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"repo": req.repo, **result}
