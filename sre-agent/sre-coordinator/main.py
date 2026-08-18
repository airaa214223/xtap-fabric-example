"""SRE coordinator — LangGraph ReAct agent orchestrating downstream HTTP services."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from mock_slack import get_alert
from tools import TRACKER, get_tools, print_baseline_summary, reset_tracker

GITHUB_AGENT_URL = os.environ.get("GITHUB_AGENT_URL", "http://github-agent:8001")
DATADOG_AGENT_URL = os.environ.get("DATADOG_AGENT_URL", "http://datadog-agent:8002")
CICD_AGENT_URL = os.environ.get("CICD_AGENT_URL", "http://cicd-agent:8003")

SYSTEM_PROMPT = """You are an SRE debugging agent responding to production alerts.

Your job:
1. Investigate the alert by querying logs and reading relevant source code.
2. Identify the root cause of the error.
3. Commit a fix via commit_fix with a clear unified diff.
4. Optionally trigger a deploy for the affected service after committing.

Guidelines:
- Start by querying Datadog logs for the service mentioned in the alert.
- Follow stack traces and error messages to find the buggy file.
- Use list_repo_files to discover files before reading them.
- When you find a bug, write a minimal unified diff and call commit_fix.
- If the alert mentions dependencies (e.g. payments-lib), it is reasonable to investigate those too.
- Explain your reasoning briefly as you work, then summarize what you fixed.

All tools call real downstream services. Use them in whatever order makes sense for the alert."""


async def wait_for_agents() -> None:
    """Block until all downstream agent services are healthy."""
    endpoints = [
        ("github-agent", f"{GITHUB_AGENT_URL}/health"),
        ("datadog-agent", f"{DATADOG_AGENT_URL}/health"),
        ("cicd-agent", f"{CICD_AGENT_URL}/health"),
    ]

    print("Waiting for downstream agents to become healthy...", flush=True)
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            all_ok = True
            for name, url in endpoints:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                except Exception:
                    all_ok = False
                    print(f"  {name} not ready yet...", flush=True)
                    break
            if all_ok:
                print("All agents healthy.\n", flush=True)
                return
            await asyncio.sleep(2)


async def poll_slack_for_alert(scenario: str) -> dict:
    """Simulate polling Slack, then return the selected mock alert fixture."""
    print("Polling Slack for alert messages...", flush=True)
    await asyncio.sleep(2)
    alert = get_alert(scenario)
    print("Alert message received.", flush=True)
    print(f"  scenario={scenario}", flush=True)
    print(f"  service={alert['service']}", flush=True)
    print(f"  message={alert['message']}\n", flush=True)
    return alert


def build_agent():
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(model=model_name, temperature=0)
    return create_react_agent(llm, get_tools(), prompt=SYSTEM_PROMPT)


async def run_investigation(alert: dict, scenario: str) -> None:
    reset_tracker()
    agent = build_agent()

    user_message = (
        f"Production alert received:\n"
        f"  Service: {alert['service']}\n"
        f"  Message: {alert['message']}\n\n"
        "Investigate this alert, find the root cause, and commit a fix."
    )

    print("--- SRE Coordinator: starting investigation ---\n", flush=True)

    final_content = ""
    async for event in agent.astream(
        {"messages": [("user", user_message)]},
        stream_mode="values",
    ):
        messages = event.get("messages", [])
        if messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content and getattr(last, "type", None) == "ai":
                final_content = content
                print(f"[agent] {content}\n", flush=True)

    if "FIX COMMITTED" not in final_content and TRACKER.repos_committed:
        for repo in sorted(TRACKER.repos_committed):
            print(f"FIX COMMITTED to {repo} (see tool output above)", flush=True)

    print_baseline_summary(scenario)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SRE debugging demo coordinator")
    parser.add_argument(
        "--scenario",
        default=os.environ.get("SCENARIO", "simple"),
        choices=["simple", "complicated"],
        help="Alert scenario to inject (default: simple, or SCENARIO env var)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    scenario = args.scenario

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable is required.", flush=True)
        sys.exit(1)

    await wait_for_agents()
    alert = await poll_slack_for_alert(scenario)
    await run_investigation(alert, scenario)


if __name__ == "__main__":
    asyncio.run(main())
