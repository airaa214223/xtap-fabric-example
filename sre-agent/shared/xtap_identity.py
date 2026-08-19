"""Shared enroll + peer client_id helpers for the four SRE demo processes.

Assumption (flagged): peer ACT client_ids are distributed via environment
variables, with a shared directory as fallback so first-run Compose can
discover ids after each process enrolls. The SDK has no directory service.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from xtap_fabric import Agent, IncomingTaskValidationResult, check_act_health

# Logical agent_id (identity folder name) per process.
AGENT_SRE = "sre-coordinator"
AGENT_GITHUB = "github-agent"
AGENT_DATADOG = "datadog-agent"
AGENT_CICD = "cicd-agent"

_SOFTWARE_ENV: dict[str, tuple[str, str]] = {
    AGENT_SRE: ("SRE_COORDINATOR_SOFTWARE_ID", "SRE_COORDINATOR_SOFTWARE_SECRET"),
    AGENT_GITHUB: ("GITHUB_AGENT_SOFTWARE_ID", "GITHUB_AGENT_SOFTWARE_SECRET"),
    AGENT_DATADOG: ("DATADOG_AGENT_SOFTWARE_ID", "DATADOG_AGENT_SOFTWARE_SECRET"),
    AGENT_CICD: ("CICD_AGENT_SOFTWARE_ID", "CICD_AGENT_SOFTWARE_SECRET"),
}

_CLIENT_ID_ENV: dict[str, str] = {
    AGENT_SRE: "SRE_COORDINATOR_CLIENT_ID",
    AGENT_GITHUB: "GITHUB_AGENT_CLIENT_ID",
    AGENT_DATADOG: "DATADOG_AGENT_CLIENT_ID",
    AGENT_CICD: "CICD_AGENT_CLIENT_ID",
}

_NAMES: dict[str, tuple[str, str]] = {
    AGENT_SRE: (
        "SRE coordinator",
        "LangGraph coordinator that investigates alerts via enrolled specialists",
    ),
    AGENT_GITHUB: ("GitHub agent", "Mock GitHub specialist that reads and commits repos"),
    AGENT_DATADOG: ("Datadog agent", "Mock Datadog specialist that queries service logs"),
    AGENT_CICD: ("CI/CD agent", "Mock CI/CD specialist that triggers deploys"),
}


def load_dotenv_if_present() -> None:
    """Load a repo-root or cwd .env without overriding existing process env."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
    ]
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        _apply_env_file(resolved)


def _apply_env_file(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


def apply_software_credentials(agent_id: str) -> None:
    """Map per-service SOFTWARE_* names onto XTAP_SOFTWARE_ID / SECRET if unset."""
    pair = _SOFTWARE_ENV.get(agent_id)
    if pair is None:
        return
    id_key, secret_key = pair
    if not os.environ.get("XTAP_SOFTWARE_ID") and os.environ.get(id_key):
        os.environ["XTAP_SOFTWARE_ID"] = os.environ[id_key]
    if not os.environ.get("XTAP_SOFTWARE_SECRET") and os.environ.get(secret_key):
        os.environ["XTAP_SOFTWARE_SECRET"] = os.environ[secret_key]


def client_id_dir() -> Path:
    raw = os.environ.get("XTAP_CLIENT_ID_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent.parent / "data" / "client-ids"


def publish_client_id(agent_id: str, client_id: str) -> None:
    env_name = _CLIENT_ID_ENV[agent_id]
    print(f"{env_name}={client_id}", flush=True)
    directory = client_id_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / agent_id).write_text(client_id, encoding="utf-8")


def read_peer_client_id(agent_id: str) -> str | None:
    env_name = _CLIENT_ID_ENV[agent_id]
    from_env = os.environ.get(env_name, "").strip()
    if from_env:
        return from_env
    path = client_id_dir() / agent_id
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    return None


def wait_for_peer_client_ids(agent_ids: list[str], *, timeout: float = 120.0) -> dict[str, str]:
    """Block until each peer has published an ACT client_id (env or shared file)."""
    deadline = time.monotonic() + timeout
    missing = list(agent_ids)
    print("Waiting for peer ACT client_ids...", flush=True)
    while missing:
        still: list[str] = []
        for agent_id in missing:
            if read_peer_client_id(agent_id):
                print(f"  {agent_id}: ok", flush=True)
            else:
                still.append(agent_id)
        if not still:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Timed out waiting for ACT client_ids for: " + ", ".join(still)
            )
        print(f"  still waiting: {', '.join(still)}", flush=True)
        time.sleep(2)
        missing = still
    return {agent_id: read_peer_client_id(agent_id) or "" for agent_id in agent_ids}


def enroll_agent(agent_id: str) -> Agent:
    """Health-check ACT, load-or-enroll, and publish client_id. Sync (no running loop)."""
    apply_software_credentials(agent_id)
    check_act_health()
    agent_name, description = _NAMES[agent_id]
    agent = Agent.load_or_enroll_from_env(
        agent_id,
        agent_name=agent_name,
        description=description,
    )
    print(f"Enrolled {agent_id} client_id={agent.client_id}", flush=True)
    publish_client_id(agent_id, agent.client_id)
    return agent


async def enroll_agent_async(agent_id: str) -> Agent:
    """Async twin for processes that already have an event loop."""
    from xtap_fabric import check_act_health_async

    apply_software_credentials(agent_id)
    await check_act_health_async()
    agent_name, description = _NAMES[agent_id]
    agent = await Agent.load_or_enroll_from_env_async(
        agent_id,
        agent_name=agent_name,
        description=description,
    )
    print(f"Enrolled {agent_id} client_id={agent.client_id}", flush=True)
    publish_client_id(agent_id, agent.client_id)
    return agent


def require_coordinator_presenter(incoming: object) -> None:
    """Allowlist: intra-domain DPoP from the SRE coordinator (shared field + type)."""
    from fastapi import HTTPException

    expected = read_peer_client_id(AGENT_SRE)
    immediate_sender = getattr(incoming, "immediate_sender", None)
    if expected is None:
        raise HTTPException(
            status_code=503,
            detail="SRE_COORDINATOR_CLIENT_ID is not available yet",
        )
    if immediate_sender != expected:
        raise HTTPException(status_code=403, detail="unexpected presenter")
    if not isinstance(incoming, IncomingTaskValidationResult):
        raise HTTPException(
            status_code=403,
            detail="expected intra-domain DPoP presentation",
        )
