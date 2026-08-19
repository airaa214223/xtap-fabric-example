"""Async LangGraph tools that call enrolled specialist agents over A2A hops."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_shared = Path(__file__).resolve().parent.parent / "shared"
if (_shared / "xtap_identity.py").is_file() and str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

from langchain_core.tools import tool

from fabric_session import FabricSession
from xtap_identity import AGENT_CICD, AGENT_DATADOG, AGENT_GITHUB

# Team ownership for narration (checkout-service owns the alert).
ALERT_OWNER = "checkout-service"
OUT_OF_SCOPE_REPOS = {"payments-lib"}


@dataclass
class CallTracker:
    """Records outbound calls for live visibility and end-of-run narration."""

    calls: list[str] = field(default_factory=list)
    repos_read: set[str] = field(default_factory=set)
    repos_committed: set[str] = field(default_factory=set)
    services_queried: set[str] = field(default_factory=set)
    products_deployed: set[str] = field(default_factory=set)

    def log(self, message: str) -> None:
        print(message, flush=True)
        self.calls.append(message)


TRACKER = CallTracker()
_SESSION: FabricSession | None = None


def bind_fabric_session(session: FabricSession) -> None:
    """Attach the consented Fabric session used by tools for A2A hops."""
    global _SESSION
    _SESSION = session


def _session() -> FabricSession:
    if _SESSION is None:
        raise RuntimeError("Fabric session is not bound; consent before invoking tools")
    return _SESSION


@tool
async def query_datadog_logs(service: str) -> str:
    """Query Datadog logs for a service. Use this to investigate errors and stack traces."""
    TRACKER.log(f"[call] POST datadog-agent/query -> service={service}")
    TRACKER.services_queried.add(service)

    data = await _session().a2a_request(
        AGENT_DATADOG,
        "POST",
        "/query",
        params={"service": service},
    )

    logs = data.get("logs", [])
    if not logs:
        return f"No logs found for service '{service}'."
    return "\n".join(logs)


@tool
async def list_repo_files(repo: str) -> str:
    """List file paths in a GitHub repository. Use before reading specific files."""
    TRACKER.log(f"[call] GET github-agent/list -> repo={repo}")

    data = await _session().a2a_request(
        AGENT_GITHUB,
        "GET",
        "/list",
        params={"repo": repo},
    )

    files = data.get("files", [])
    TRACKER.repos_read.add(repo)
    return json.dumps({"repo": repo, "files": files}, indent=2)


@tool
async def read_repo_file(repo: str, path: str) -> str:
    """Read a file from a GitHub repository. Use to inspect source code for bugs."""
    TRACKER.log(f"[call] GET github-agent/read -> repo={repo}, path={path}")

    data = await _session().a2a_request(
        AGENT_GITHUB,
        "GET",
        "/read",
        params={"repo": repo, "path": path},
    )

    TRACKER.repos_read.add(repo)
    content = data.get("content", "")
    return f"--- {repo}/{path} ---\n{content}"


@tool
async def commit_fix(repo: str, diff: str, description: str) -> str:
    """Commit and push a fix to a GitHub repository. Provide a unified diff and short description."""
    TRACKER.log(
        f"[call] POST github-agent/commit -> repo={repo}, description={description!r}"
    )

    data = await _session().a2a_request(
        AGENT_GITHUB,
        "POST",
        "/commit",
        json_body={"repo": repo, "diff": diff},
    )

    TRACKER.repos_committed.add(repo)
    mr_url = data.get("mr_url", "unknown")
    commit_sha = data.get("commit_sha", "unknown")
    return (
        f"FIX COMMITTED to {repo}\n"
        f"  MR URL: {mr_url}\n"
        f"  Commit: {commit_sha}\n"
        f"  Description: {description}"
    )


@tool
async def trigger_deploy(product: str) -> str:
    """Trigger a CI/CD deploy for a product/service after a fix is committed."""
    TRACKER.log(f"[call] POST cicd-agent/deploy -> product={product}")
    TRACKER.products_deployed.add(product)

    data = await _session().a2a_request(
        AGENT_CICD,
        "POST",
        "/deploy",
        json_body={"product": product},
    )

    return json.dumps(data, indent=2)


def get_tools() -> list:
    return [
        query_datadog_logs,
        list_repo_files,
        read_repo_file,
        commit_fix,
        trigger_deploy,
    ]


def reset_tracker() -> None:
    global TRACKER
    TRACKER = CallTracker()


def print_baseline_summary(scenario: str) -> None:
    """Print end-of-run narration, especially for cross-boundary access."""
    out_of_scope_read = TRACKER.repos_read & OUT_OF_SCOPE_REPOS
    out_of_scope_committed = TRACKER.repos_committed & OUT_OF_SCOPE_REPOS

    print("\n" + "=" * 60, flush=True)
    print("=== Fabric run complete ===", flush=True)
    print(f"Scenario: {scenario}", flush=True)
    print(f"Alert owner service: {ALERT_OWNER}", flush=True)
    print(f"Services queried: {sorted(TRACKER.services_queried) or '(none)'}", flush=True)
    print(f"Repos read: {sorted(TRACKER.repos_read) or '(none)'}", flush=True)
    print(f"Repos committed: {sorted(TRACKER.repos_committed) or '(none)'}", flush=True)

    if scenario == "complicated" and (out_of_scope_read or out_of_scope_committed):
        parts: list[str] = []
        if out_of_scope_read:
            parts.append(f"read {', '.join(sorted(out_of_scope_read))}")
        if out_of_scope_committed:
            parts.append(f"modified {', '.join(sorted(out_of_scope_committed))}")
        action = " and ".join(parts)
        print(
            f"\nThis agent {action}, "
            f"repositories outside the team that owns this alert ({ALERT_OWNER}). "
            "A2A hops were identity-bound; repo ownership is not an ACT action in this demo.",
            flush=True,
        )
    elif scenario == "simple":
        if out_of_scope_read or out_of_scope_committed:
            print(
                "\nNote: unexpected cross-boundary access occurred in the simple scenario.",
                flush=True,
            )
        else:
            print(
                "\nInvestigation stayed within checkout-service ownership. "
                "Repo ownership is still application policy, not an ACT action.",
                flush=True,
            )

    print("=" * 60 + "\n", flush=True)
