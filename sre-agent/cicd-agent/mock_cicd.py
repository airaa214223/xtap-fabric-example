"""In-memory mock CI/CD API."""

from __future__ import annotations

from typing import Any

DEPLOY_STATUS: dict[str, dict[str, Any]] = {}


def trigger_deploy(product: str) -> dict[str, str]:
    """Flip in-memory deploy status and return a fake response."""
    DEPLOY_STATUS[product] = {"status": "deploying", "product": product}
    return {"status": "deploying", "product": product}
