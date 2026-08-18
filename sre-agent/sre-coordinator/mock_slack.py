"""Mock Slack alert fixtures — selectable via scenario flag."""

from __future__ import annotations

from typing import Any

ALERT_SIMPLE: dict[str, Any] = {
    "service": "checkout-service",
    "message": "500 errors spiking on checkout-service",
}

ALERT_COMPLICATED: dict[str, Any] = {
    "service": "checkout-service",
    "message": (
        "500 errors spiking on checkout-service, possible dependency on payments-lib"
    ),
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "simple": ALERT_SIMPLE,
    "complicated": ALERT_COMPLICATED,
}


def get_alert(scenario: str) -> dict[str, Any]:
    """Return the alert fixture for the given scenario name."""
    if scenario not in SCENARIOS:
        valid = ", ".join(sorted(SCENARIOS))
        raise ValueError(f"Unknown scenario '{scenario}'. Choose one of: {valid}")
    return SCENARIOS[scenario].copy()
