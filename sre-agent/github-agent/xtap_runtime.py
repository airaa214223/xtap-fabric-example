"""XTap Fabric helpers used by this process only (not imported across services)."""

from __future__ import annotations

import asyncio
import inspect
import os
from typing import Any, Callable

CONSENT_PORT = int(os.environ.get("XTAP_CONSENT_PORT", "8765"))
REDIRECT_URI = os.environ.get(
    "XTAP_REDIRECT_URI",
    f"http://127.0.0.1:{CONSENT_PORT}/callback",
)

_agent: Any = None
_authority: Any = None
_receiver_client_ids: dict[str, str] = {}
_fabric_loop: asyncio.AbstractEventLoop | None = None


def get_agent() -> Any:
    return _agent


def get_authority() -> Any:
    return _authority


def set_context(agent: Any, authority: Any | None = None) -> None:
    global _agent, _authority, _fabric_loop
    _agent = agent
    _authority = authority
    try:
        _fabric_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass


def set_receiver_client_id(name: str, client_id: str | None) -> None:
    if client_id:
        _receiver_client_ids[name] = client_id
        print(f"Receiver {name} client_id={client_id}", flush=True)


def receiver_resource(name: str, fallback: str) -> str:
    """Audience for delegate_subtask: enrolled receiver client_id, else URL."""
    return _receiver_client_ids.get(name) or fallback


def fabric_issuer() -> str:
    return (
        os.environ.get("XTAP_FABRIC_ISSUER")
        or os.environ.get("XTAP_URL")
        or os.environ.get("ACT_BASE_URL")
        or ""
    ).rstrip("/")


def fabric_jwks_url() -> str:
    explicit = os.environ.get("XTAP_FABRIC_JWKS_URL")
    if explicit:
        return explicit
    issuer = fabric_issuer()
    return f"{issuer}/.well-known/jwks.json" if issuer else ""


def health_payload() -> dict[str, str]:
    payload = {"status": "ok"}
    client_id = getattr(get_agent(), "client_id", None)
    if client_id:
        payload["client_id"] = str(client_id)
    return payload


def _filter_kwargs(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return {k: v for k, v in kwargs.items() if v is not None}
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return {k: v for k, v in kwargs.items() if v is not None}
    allowed = {
        name
        for name in sig.parameters
        if name not in ("self", "cls")
    }
    return {k: v for k, v in kwargs.items() if k in allowed and v is not None}


def run_on_fabric_loop(coro: Any) -> Any:
    """Run a Fabric coroutine on the loop that owns the agent's HTTP client.

    wrap_signed sync tools run in a worker thread. The sync ``delegate_subtask``
    twin uses a *different* background loop, which cannot reuse the httpx
    client created at enroll time.
    """
    loop = _fabric_loop
    if loop is None or not loop.is_running():
        return asyncio.run(coro)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        coro.close()
        raise RuntimeError(
            "Cannot block the fabric event loop; call the async twin instead"
        )
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)


async def call_maybe_async(obj: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    """Call `name_async` if present, else `name`, awaiting a coroutine result."""
    fn = getattr(obj, f"{name}_async", None)
    if fn is None:
        fn = getattr(obj, name)
    result = fn(*args, **_filter_kwargs(fn, kwargs))
    if inspect.isawaitable(result):
        return await result
    return result


async def enroll_this_agent(agent_id: str, agent_name: str, description: str) -> Any:
    from xtap_fabric import Agent, AgentConfig, check_act_health_async

    print(f"Checking ACT health for {agent_id}...", flush=True)
    await check_act_health_async()
    cfg = AgentConfig.from_env()
    agent = await call_maybe_async(
        Agent,
        "load_or_enroll",
        agent_id,
        agent_name=agent_name,
        description=description,
        xtap_url=cfg.xtap_url,
        software_secret=cfg.software_secret,
        software_id=cfg.software_id,
        tenant_id=cfg.tenant_id,
        key_passphrase=cfg.key_passphrase,
        state_dir=cfg.state_dir,
    )
    client_id = getattr(agent, "client_id", None)
    print(f"Enrolled {agent_id} client_id={client_id}", flush=True)
    set_context(agent)
    return agent


def _print_authorize_url(url: str) -> None:
    print(f"Open and Approve: {url}", flush=True)


async def consent_for_task(agent: Any, task_content: str) -> Any:
    """Mode A consent. Prints the URL; does not open a browser."""
    authority = await call_maybe_async(
        agent,
        "consent_via_local_browser",
        task_content,
        ["read", "complete"],
        resource=getattr(agent, "client_id", None),
        open_browser=False,
        on_authorize_url=_print_authorize_url,
        redirect_uri=REDIRECT_URI,
        port=CONSENT_PORT,
        callback_port=CONSENT_PORT,
        listen_port=CONSENT_PORT,
        host="0.0.0.0",
        bind_host="0.0.0.0",
        listen_host="0.0.0.0",
    )
    set_context(agent, authority)
    return authority


async def complete_current_task() -> None:
    agent = get_agent()
    authority = get_authority()
    if agent is None or authority is None:
        return
    task_id = getattr(authority, "task_id", None)
    if task_id is None:
        return
    await call_maybe_async(agent, "complete_task", task_id)


async def accept_incoming_from_request(agent: Any, request: Any) -> None:
    """Bind the presented token/DPoP from an inbound HTTP request."""
    from xtap_fabric.types.credentials import TokenType
    from xtap_fabric.types.receive import IncomingTaskRequestContext

    authorization = request.headers.get("authorization") or ""
    dpop = request.headers.get("dpop")
    scheme, _, token = authorization.partition(" ")
    token = token.strip() or authorization.strip()
    scheme_l = scheme.lower()
    token_type = TokenType.BEARER if scheme_l == "bearer" else TokenType.DPOP
    issuer = fabric_issuer()
    sender = request.headers.get("x-xtap-immediate-sender")
    context = IncomingTaskRequestContext(
        http_method=request.method,
        http_uri=str(request.url),
        expected_audience=getattr(agent, "client_id", None),
        expected_issuer=issuer or None,
        expected_immediate_sender=sender,
        presented_token_type=token_type,
        task_id=request.headers.get("x-xtap-task-id"),
    )
    await call_maybe_async(
        agent,
        "accept_incoming_task",
        task_token=token or None,
        dpop_proof=dpop,
        context=context,
        fabric_issuer=issuer or None,
        fabric_jwks_url=fabric_jwks_url() or None,
    )


def install_accept_middleware(app: Any, skip_paths: frozenset[str] | None = None) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    protected_skip = skip_paths or frozenset(
        {"/health", "/docs", "/openapi.json", "/redoc"}
    )

    @app.middleware("http")
    async def _accept_incoming(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path in protected_skip:
            return await call_next(request)
        agent = getattr(request.app.state, "xtap_agent", None) or get_agent()
        if agent is None:
            return JSONResponse(
                status_code=503,
                content={"detail": "Agent identity is not enrolled yet"},
            )
        try:
            await accept_incoming_from_request(agent, request)
        except Exception as exc:
            print(f"[fabric] accept_incoming_task failed: {exc}", flush=True)
            return JSONResponse(
                status_code=401,
                content={"detail": f"accept_incoming_task failed: {exc}"},
            )
        return await call_next(request)


def hop_then_request(
    *,
    method: str,
    url: str,
    task_content: str,
    actions: list[str],
    resource: str,
    **http_kwargs: Any,
) -> Any:
    """Delegate on ACT, present DPoP materials, then HTTP to the specialist."""
    import httpx

    agent = get_agent()
    authority = get_authority()
    timeout = http_kwargs.pop("timeout", 30.0)
    extra_headers = dict(http_kwargs.pop("headers", None) or {})
    http_method = method.upper()

    params = http_kwargs.get("params")
    htu = str(httpx.URL(url, params=params)) if params else url

    print(
        f"[fabric] delegate_subtask -> {task_content} resource={resource}",
        flush=True,
    )

    async def _delegate_and_present() -> Any:
        child = await call_maybe_async(
            agent,
            "delegate_subtask",
            task_content,
            actions,
            resource,
            parent_authority=authority,
        )
        return agent.prepare_a2a_presentation(
            http_method=http_method,
            http_uri=htu,
            authority=child,
            task_id=getattr(child, "task_id", None),
        )

    if agent is None:
        raise RuntimeError("Fabric agent is not enrolled")
    materials = run_on_fabric_loop(_delegate_and_present())
    extra_headers["Authorization"] = materials.authorization
    if materials.dpop_proof:
        extra_headers["DPoP"] = materials.dpop_proof
    extra_headers["X-XTAP-Immediate-Sender"] = str(agent.client_id)
    print(f"[fabric] A2A present {http_method} {htu}", flush=True)

    with httpx.Client(timeout=timeout) as http:
        return http.request(http_method, url, headers=extra_headers, **http_kwargs)
