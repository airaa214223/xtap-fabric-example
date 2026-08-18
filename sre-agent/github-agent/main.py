"""GitHub agent — plain FastAPI wrapper over mock_github."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from mock_github import commit_and_push, list_files, read_repo

app = FastAPI(title="github-agent", version="0.1.0")


class CommitRequest(BaseModel):
    repo: str
    diff: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
