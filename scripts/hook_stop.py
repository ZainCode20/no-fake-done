#!/usr/bin/env python3
"""Stop-hook wrapper for slop-guard (supports Antigravity and Claude Code).

Reads hook context JSON from stdin, audits the target git repository for
CRITICAL AI slop findings, and blocks premature completion once per turn.
Never blocks non-git workspaces, clean diffs, or already-continued turns.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_diff  # noqa: E402


def _read_stdin_json() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _resolve_repo_path(payload: dict) -> Path:
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return Path(cwd)
    workspaces = payload.get("workspacePaths")
    if isinstance(workspaces, list) and workspaces and isinstance(workspaces[0], str):
        return Path(workspaces[0])
    return Path(".")


def evaluate_stop_hook(payload: dict, mode: str) -> dict:
    """Evaluate a Stop hook payload and return the JSON decision object."""
    if mode == "antigravity":
        if payload.get("continuationActive"):
            return {}
        reason = payload.get("terminationReason")
        if reason and reason != "NO_TOOL_CALL":
            return {}
    else:
        if payload.get("stop_hook_active"):
            return {}

    repo = _resolve_repo_path(payload)
    try:
        diff_text = audit_diff._run_git_diff(base=None, repo=repo, include_untracked=True)
    except (OSError, RuntimeError):
        return {}

    findings = audit_diff.audit_unified_diff(diff_text)
    critical = [f for f in findings if f.severity == "CRITICAL"]
    if not critical:
        return {}

    report = audit_diff.format_human_report(critical)
    decision_value = "continue" if mode == "antigravity" else "block"
    return {
        "decision": decision_value,
        "reason": (
            "slop-guard detected CRITICAL issues in your diff before completion. "
            "Fix these issues and re-run tests before finishing:\n"
            f"{report}"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="slop-guard Stop hook handler.")
    parser.add_argument(
        "--mode",
        choices=("antigravity", "claude"),
        default="antigravity",
        help="Target agent hook protocol.",
    )
    args = parser.parse_args(argv)

    payload = _read_stdin_json()
    result = evaluate_stop_hook(payload, mode=args.mode)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
