"""In-memory mock Datadog API."""

from __future__ import annotations

LOGS: dict[str, list[str]] = {
    "checkout-service": [
        "2026-08-17T10:01:12Z ERROR checkout-service request_id=req-8f2a status=500 path=/checkout",
        "2026-08-17T10:01:13Z ERROR checkout-service TypeError: 'bool' object is not subscriptable",
        '2026-08-17T10:01:13Z ERROR checkout-service   File "src/handlers/checkout.py", line 9, in process_checkout',
        "2026-08-17T10:01:13Z ERROR checkout-service     if not validation['valid']:",
        "2026-08-17T10:01:14Z WARN  checkout-service 500 error rate spiking — 847 errors/min",
        "2026-08-17T10:01:15Z INFO  checkout-service dependency payments-lib@2.1.0 loaded",
    ],
    "payments-lib": [
        "2026-08-17T10:00:58Z INFO  payments-lib validate_card called token=****1234 result=True",
        "2026-08-17T10:01:00Z INFO  payments-lib no errors in last 15m — p99 latency 12ms",
    ],
}


def query_logs(service: str) -> list[str]:
    """Return mock log lines for the given service."""
    if service not in LOGS:
        return [f"No logs found for service '{service}'"]
    return LOGS[service]
