"""GitHub agent — FastAPI wrapper over mock_github, with inbound A2A verification."""

from __future__ import annotations

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parent.parent / "shared"
if (_shared / "xtap_identity.py").is_file() and str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from xtap_fabric_starlette import IncomingTaskMiddleware

from mock_github import commit_and_push, list_files, read_repo
from xtap_identity import AGENT_GITHUB, enroll_agent, load_dotenv_if_present, require_coordinator_presenter

load_dotenv_if_present()
_agent = enroll_agent(AGENT_GITHUB)

app = FastAPI(title="github-agent", version="0.1.0")
app.add_middleware(
    IncomingTaskMiddleware,
    agent=_agent,
    skip_paths=["/health"],
)


class CommitRequest(BaseModel):
    repo: str
    diff: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/read")
def read_file(
    request: Request,
    repo: str = Query(..., description="Repository name"),
    path: str = Query(..., description="File path within the repo"),
) -> dict[str, str]:
    require_coordinator_presenter(request.state.xtap_incoming)
    try:
        content = read_repo(repo, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"repo": repo, "path": path, "content": content}


@app.get("/list")
def list_repo_files(
    request: Request,
    repo: str = Query(..., description="Repository name"),
) -> dict:
    require_coordinator_presenter(request.state.xtap_incoming)
    try:
        files = list_files(repo)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"repo": repo, "files": files}


@app.post("/commit")
def commit(request: Request, req: CommitRequest) -> dict:
    require_coordinator_presenter(request.state.xtap_incoming)
    try:
        result = commit_and_push(req.repo, req.diff)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"repo": req.repo, **result}
