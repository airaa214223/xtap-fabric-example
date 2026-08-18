"""LangGraph tools: signed HTTP to specialist agents, with an ACT hop per call."""

import json
import os

from xtap_runtime import hop_then_request, receiver_resource

GITHUB_AGENT_URL = os.environ.get("GITHUB_AGENT_URL", "http://github-agent:8001")
DATADOG_AGENT_URL = os.environ.get("DATADOG_AGENT_URL", "http://datadog-agent:8002")
CICD_AGENT_URL = os.environ.get("CICD_AGENT_URL", "http://cicd-agent:8003")

ALERT_OWNER = "checkout-service"
OUT_OF_SCOPE_REPOS = {"payments-lib"}


class CallTracker:
    """Records outbound calls for live visibility and end-of-run narration."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.repos_read: set[str] = set()
        self.repos_committed: set[str] = set()
        self.services_queried: set[str] = set()
        self.products_deployed: set[str] = set()

    def log(self, message: str) -> None:
        print(message, flush=True)
        self.calls.append(message)


TRACKER = CallTracker()


def query_datadog_logs(service: str) -> str:
    """Query Datadog logs for a service. Use this to investigate errors and stack traces."""
    TRACKER.log(f"[call] POST datadog-agent/query -> service={service}")
    TRACKER.services_queried.add(service)
    response = hop_then_request(
        method="post",
        url=f"{DATADOG_AGENT_URL}/query",
        task_content=f"Query Datadog logs for service {service}",
        actions=["read"],
        resource=receiver_resource("datadog-agent", DATADOG_AGENT_URL),
        params={"service": service},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    logs = data.get("logs", [])
    if not logs:
        return f"No logs found for service '{service}'."
    return "\n".join(logs)


def list_repo_files(repo: str) -> str:
    """List file paths in a GitHub repository. Use before reading specific files."""
    TRACKER.log(f"[call] GET github-agent/list -> repo={repo}")
    response = hop_then_request(
        method="get",
        url=f"{GITHUB_AGENT_URL}/list",
        task_content=f"List files in repo {repo}",
        actions=["read"],
        resource=receiver_resource("github-agent", GITHUB_AGENT_URL),
        params={"repo": repo},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    files = data.get("files", [])
    TRACKER.repos_read.add(repo)
    return json.dumps({"repo": repo, "files": files}, indent=2)


def read_repo_file(repo: str, path: str) -> str:
    """Read a file from a GitHub repository. Use to inspect source code for bugs."""
    TRACKER.log(f"[call] GET github-agent/read -> repo={repo}, path={path}")
    response = hop_then_request(
        method="get",
        url=f"{GITHUB_AGENT_URL}/read",
        task_content=f"Read {repo}/{path}",
        actions=["read"],
        resource=receiver_resource("github-agent", GITHUB_AGENT_URL),
        params={"repo": repo, "path": path},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    TRACKER.repos_read.add(repo)
    content = data.get("content", "")
    return f"--- {repo}/{path} ---\n{content}"


def commit_fix(repo: str, diff: str, description: str) -> str:
    """Commit and push a fix to a GitHub repository. Provide a unified diff and short description."""
    TRACKER.log(
        f"[call] POST github-agent/commit -> repo={repo}, description={description!r}"
    )
    response = hop_then_request(
        method="post",
        url=f"{GITHUB_AGENT_URL}/commit",
        task_content=f"Commit fix to {repo}: {description}",
        actions=["read", "complete"],
        resource=receiver_resource("github-agent", GITHUB_AGENT_URL),
        json={"repo": repo, "diff": diff},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    TRACKER.repos_committed.add(repo)
    mr_url = data.get("mr_url", "unknown")
    commit_sha = data.get("commit_sha", "unknown")
    return (
        f"FIX COMMITTED to {repo}\n"
        f"  MR URL: {mr_url}\n"
        f"  Commit: {commit_sha}\n"
        f"  Description: {description}"
    )


def trigger_deploy(product: str) -> str:
    """Trigger a CI/CD deploy for a product/service after a fix is committed."""
    TRACKER.log(f"[call] POST cicd-agent/deploy -> product={product}")
    TRACKER.products_deployed.add(product)
    response = hop_then_request(
        method="post",
        url=f"{CICD_AGENT_URL}/deploy",
        task_content=f"Trigger deploy for product {product}",
        actions=["read", "complete"],
        resource=receiver_resource("cicd-agent", CICD_AGENT_URL),
        json={"product": product},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    return json.dumps(data, indent=2)


TOOL_FUNCTIONS = [
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
            "Each hop was an enrolled identity + signed HTTP + accept_incoming_task; "
            "nothing in this demo scoped the agent away from payments-lib.",
            flush=True,
        )
    elif scenario == "simple":
        print(
            "\nInvestigation used Fabric identity, consent, and signed hops. "
            "No repo-scope policy was applied.",
            flush=True,
        )

    print("=" * 60 + "\n", flush=True)
