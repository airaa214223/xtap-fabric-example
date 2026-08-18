"""In-memory mock GitHub API — no real git involved."""

from __future__ import annotations

from typing import Any

# In-memory repos keyed by repo name.
REPOS: dict[str, dict[str, str]] = {
    "checkout-service": {
        "src/handlers/checkout.py": '''"""Checkout HTTP handlers."""

from payments_lib import validate_card

def process_checkout(cart_id: str, card_token: str) -> dict:
    """Process a checkout request."""
    # BUG: validate_card returns a bool but we treat the result as a dict
    validation = validate_card(card_token)
    if not validation["valid"]:
        raise ValueError("Invalid card")

    return {"status": "ok", "cart_id": cart_id}
''',
        "src/config.py": '''"""Checkout service configuration."""

SERVICE_NAME = "checkout-service"
PAYMENTS_LIB_VERSION = "2.1.0"
''',
        "requirements.txt": "payments-lib>=2.0.0\n",
    },
    "payments-lib": {
        "payments_lib/validator.py": '''"""Payment card validation — owned by Payments team."""

import re

CARD_PATTERN = re.compile(r"^[0-9]{13,19}$")


def validate_card(card_token: str) -> bool:
    """Return True if the card token looks valid."""
    if not card_token:
        return False
    return bool(CARD_PATTERN.match(card_token.strip()))


def charge_card(card_token: str, amount_cents: int) -> dict:
    """Charge a card (unrelated to checkout bug)."""
    if not validate_card(card_token):
        return {"charged": False, "reason": "invalid_card"}
    return {"charged": True, "amount_cents": amount_cents}
''',
        "payments_lib/__init__.py": '''from payments_lib.validator import validate_card, charge_card

__all__ = ["validate_card", "charge_card"]
''',
    },
}

# Append-only commit log per repo.
COMMIT_LOG: dict[str, list[dict[str, Any]]] = {
    "checkout-service": [],
    "payments-lib": [],
}


def read_repo(repo: str, path: str) -> str:
    """Return fake file content for repo/path."""
    repo_files = REPOS.get(repo)
    if repo_files is None:
        raise FileNotFoundError(f"Repository '{repo}' not found")
    if path not in repo_files:
        raise FileNotFoundError(f"Path '{path}' not found in repo '{repo}'")
    return repo_files[path]


def list_files(repo: str) -> list[str]:
    """List file paths in a repo."""
    repo_files = REPOS.get(repo)
    if repo_files is None:
        raise FileNotFoundError(f"Repository '{repo}' not found")
    return sorted(repo_files.keys())


def commit_and_push(repo: str, diff: str) -> dict[str, str]:
    """Append a fake commit to the in-memory log."""
    if repo not in REPOS:
        raise FileNotFoundError(f"Repository '{repo}' not found")

    commit_sha = f"fake{len(COMMIT_LOG.get(repo, [])) + 1:06x}"
    entry = {"commit_sha": commit_sha, "diff": diff}
    COMMIT_LOG.setdefault(repo, []).append(entry)

    return {
        "mr_url": f"https://github.example.com/acme/{repo}/pull/{len(COMMIT_LOG[repo])}",
        "commit_sha": commit_sha,
    }
