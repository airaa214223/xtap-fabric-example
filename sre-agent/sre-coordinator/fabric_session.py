"""Coordinator-side Fabric: consent, per-specialist child tasks, A2A hops."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

_shared = Path(__file__).resolve().parent.parent / "shared"
if (_shared / "xtap_identity.py").is_file() and str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

import httpx
from xtap_fabric import Agent, ConsentTimedOutError, TaskBoundAuthority
from xtap_fabric.local_consent import LocalCallbackServer

from xtap_identity import (
    AGENT_CICD,
    AGENT_DATADOG,
    AGENT_GITHUB,
    read_peer_client_id,
)

PARENT_ACTIONS = ["read", "complete"]

_PEER_ENV_URL: dict[str, str] = {
    AGENT_GITHUB: "GITHUB_AGENT_URL",
    AGENT_DATADOG: "DATADOG_AGENT_URL",
    AGENT_CICD: "CICD_AGENT_URL",
}


class FabricSession:
    """One parent task per Slack message; one new child task per HTTP hop (no reuse)."""

    def __init__(self, agent: Agent, parent: TaskBoundAuthority) -> None:
        self.agent = agent
        self.parent = parent
        self._children: list[tuple[str, TaskBoundAuthority]] = []
        self._lock = asyncio.Lock()
        if not parent.task_id:
            raise RuntimeError("parent TaskBoundAuthority is missing task_id")

    async def a2a_request(
        self,
        peer_agent_id: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        base = os.environ.get(
            _PEER_ENV_URL[peer_agent_id],
            {
                AGENT_GITHUB: "http://github-agent:8001",
                AGENT_DATADOG: "http://datadog-agent:8002",
                AGENT_CICD: "http://cicd-agent:8003",
            }[peer_agent_id],
        ).rstrip("/")
        url = f"{base}{path}"
        child = await self._delegate_hop(peer_agent_id, method, path, params, json_body)
        if not child.task_id:
            raise RuntimeError(f"child task for {peer_agent_id} {method} {path} is missing task_id")

        async with httpx.AsyncClient(timeout=30.0) as client:
            request = client.build_request(method, url, params=params, json=json_body)
            http_uri = str(request.url)
            materials = await self.agent.prepare_a2a_presentation_async(
                http_method=method,
                http_uri=http_uri,
                task_id=child.task_id,
            )
            request.headers["Authorization"] = materials.authorization
            if materials.dpop_proof is not None:
                request.headers["DPoP"] = materials.dpop_proof
            response = await client.send(request)
            response.raise_for_status()
            return response.json()

    async def _delegate_hop(
        self,
        peer_agent_id: str,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        json_body: Any,
    ) -> TaskBoundAuthority:
        resource = read_peer_client_id(peer_agent_id)
        if not resource:
            raise RuntimeError(
                f"missing ACT client_id for {peer_agent_id} "
                f"(set {_peer_client_env(peer_agent_id)} or the shared client-id file)"
            )
        async with self._lock:
            delegated = await self.agent.delegate_subtask_async(
                _hop_task_content(peer_agent_id, method, path, params, json_body),
                PARENT_ACTIONS,
                resource,
                parent_authority=self.parent,
            )
            if not isinstance(delegated, TaskBoundAuthority):
                raise RuntimeError(
                    f"expected intra-domain TaskBoundAuthority for {peer_agent_id}, "
                    f"got {type(delegated).__name__}"
                )
            print(
                f"[fabric] delegated hop {method} {path} to {peer_agent_id} "
                f"task_id={delegated.task_id}",
                flush=True,
            )
            self._children.append((peer_agent_id, delegated))
            return delegated

    async def complete_all(self) -> None:
        """Complete every child this process registered, then the parent."""
        for peer_id, child in self._children:
            if not child.task_id:
                continue
            try:
                await self.agent.complete_task_async(child.task_id)
                print(f"[fabric] completed child task {peer_id} {child.task_id}", flush=True)
            except Exception as exc:
                print(f"[fabric] complete child {peer_id} failed: {exc}", flush=True)
        if self.parent.task_id:
            try:
                await self.agent.complete_task_async(self.parent.task_id)
                print(f"[fabric] completed parent task {self.parent.task_id}", flush=True)
            except Exception as exc:
                print(f"[fabric] complete parent failed: {exc}", flush=True)


def _peer_client_env(agent_id: str) -> str:
    return {
        AGENT_GITHUB: "GITHUB_AGENT_CLIENT_ID",
        AGENT_DATADOG: "DATADOG_AGENT_CLIENT_ID",
        AGENT_CICD: "CICD_AGENT_CLIENT_ID",
    }[agent_id]


def _hop_task_content(
    peer_agent_id: str,
    method: str,
    path: str,
    params: dict[str, Any] | None,
    json_body: Any,
) -> str:
    parts = [f"{method} {peer_agent_id}{path}"]
    if params:
        parts.append(" ".join(f"{key}={value}" for key, value in params.items()))
    if isinstance(json_body, dict) and json_body.get("repo"):
        parts.append(f"repo={json_body['repo']}")
    if isinstance(json_body, dict) and json_body.get("product"):
        parts.append(f"product={json_body['product']}")
    return " ".join(parts)


def _print_authorize_url(url: str) -> None:
    print(
        "\n=== Mode A consent ===\n"
        "Copy this URL into your browser and Approve:\n"
        f"{url}\n",
        flush=True,
    )


async def collect_parent_authority(agent: Agent, task_content: str) -> TaskBoundAuthority:
    """Mode A: print the authorize URL; do not open a browser.

    ``consent_via_local_browser`` uses one ``host`` for both bind and
    ``redirect_uri``. Inside Compose that makes ACT redirect the host browser
    to a loopback port that exists only in the container. Bind ``0.0.0.0`` in
    Docker, advertise ``127.0.0.1`` (published) as ``redirect_uri``, using the
    SDK's ``LocalCallbackServer``.
    """
    advertise_host = os.environ.get("XTAP_CALLBACK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    default_bind = "0.0.0.0" if Path("/.dockerenv").exists() else advertise_host
    bind_host = os.environ.get("XTAP_CALLBACK_BIND_HOST", default_bind).strip() or default_bind
    port_raw = os.environ.get("XTAP_CALLBACK_PORT", "9876").strip() or "9876"
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise RuntimeError(f"XTAP_CALLBACK_PORT must be an integer, got {port_raw!r}") from exc

    callback = LocalCallbackServer(host=bind_host, port=port)
    callback.start()
    redirect_uri = f"http://{advertise_host}:{callback.port}{callback.path}"
    print(
        "[fabric] Mode A: waiting for Approve "
        f"(bind {bind_host}:{callback.port}, redirect_uri {redirect_uri}; "
        "open_browser=False)...",
        flush=True,
    )
    try:
        handle = await agent.start_consent_par_async(
            task_content,
            PARENT_ACTIONS,
            redirect_uri=redirect_uri,
        )
        authorize_url = handle.authorize_url
        if authorize_url:
            _print_authorize_url(authorize_url)
        try:
            code = await asyncio.to_thread(
                callback.wait_for_code,
                300.0,
                task_id=handle.task_id,
            )
        except TimeoutError as exc:
            raise ConsentTimedOutError(
                handle.task_id,
                timeout_seconds=300.0,
            ) from exc
        await handle.exchange_authorization_code_async(code)
        return await agent.register_main_task_async(handle, agent.client_id)
    finally:
        callback.stop()
