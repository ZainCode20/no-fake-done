#!/usr/bin/env python3
"""Deterministic git diff auditor for catching AI coding slop before completion."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

TEST_FILE_RE = re.compile(
    r"(^|[\\/])(tests?|__tests__|spec)[\\/]|"
    r"(^|[\\/])test_[^\\/]+\.[a-zA-Z0-9]+$|"
    r"(_test|\.test|\.spec)\.[a-zA-Z0-9]+$",
    re.IGNORECASE,
)

SKIP_PATTERNS = [
    re.compile(r"@pytest\.mark\.skip\b"),
    re.compile(r"@unittest\.skip\b"),
    re.compile(r"\b(test|it|describe)\.skip\s*\("),
    re.compile(r"\bx(it|describe|test)\s*\("),
    re.compile(r"@Ignore\b"),
    re.compile(r"\bt\.Skip\s*\("),
]

TRIVIAL_ASSERT_PATTERNS = [
    re.compile(r"^\s*assert\s+True\s*(#.*)?$"),
    re.compile(r"^\s*assert\s+1\s*==\s*1\s*(#.*)?$"),
    re.compile(r"^\s*expect\s*\(\s*true\s*\)\s*\.\s*toBe\s*\(\s*true\s*\)"),
    re.compile(r"^\s*expect\s*\(\s*1\s*\)\s*\.\s*toBe\s*\(\s*1\s*\)"),
]

ASSERTION_LINE_RE = re.compile(
    r"\b(assert\w*|expect|should|require)\b\s*[\(\.]|\bassert\s+",
    re.IGNORECASE,
)

STUB_PATTERNS = [
    re.compile(r"\b(TODO|FIXME|XXX|HACK)\b\s*:?"),
    re.compile(r"\braise\s+NotImplementedError\b"),
    re.compile(r"\bthrow\s+new\s+Error\s*\(\s*['\"]not implemented['\"]", re.IGNORECASE),
    re.compile(r"\b(unimplemented|todo)!\s*\("),
]

DEBUGGER_PATTERNS = [
    re.compile(r"\bbreakpoint\s*\("),
    re.compile(r"\bpdb\.set_trace\s*\("),
    re.compile(r"\bipdb\.set_trace\s*\("),
    re.compile(r"^\s*debugger\s*;?\s*$"),
]

SWALLOWED_ERROR_PATTERNS = [
    re.compile(r"^\s*except\s*:\s*(pass|\.\.\.)?\s*(#.*)?$"),
    re.compile(r"^\s*except\s+Exception(\s+as\s+\w+)?\s*:\s*(pass|\.\.\.)\s*(#.*)?$"),
    re.compile(r"\bcatch\s*(\([^)]*\))?\s*\{\s*\}"),
]

DEBUG_PRINT_PATTERNS = [
    re.compile(r"\bconsole\.(log|debug)\s*\("),
]

COMMENT_LINE_RE = re.compile(r"^\s*(#|//)\s*(.+)$")
CODE_LIKE_RE = re.compile(r"(=|\(|\)|\{|\}|;|\b(def|class|function|return|import|const|let|var)\b)")


@dataclass
class Finding:
    """Single audit finding detected in a unified diff."""

    severity: str  # "CRITICAL" | "WARNING"
    rule: str
    file: str
    line: int
    message: str
    snippet: str = ""


def is_test_file(filepath: str) -> bool:
    """Return True if the file path matches common test-file conventions."""
    return bool(TEST_FILE_RE.search(filepath))


def _run_git_diff(base: str | None) -> str:
    """Collect unified diff from git (against base ref, HEAD, or working tree)."""
    if base:
        cmd = ["git", "diff", "--no-color", "-U3", base]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"git diff failed for base '{base}'")
        return proc.stdout

    has_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).returncode == 0

    if has_head:
        proc = subprocess.run(["git", "diff", "--no-color", "-U3", "HEAD"], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git diff HEAD failed")
        return proc.stdout

    # Fallback for repositories with no commits yet: combine unstaged + staged diffs.
    unstaged = subprocess.run(["git", "diff", "--no-color", "-U3"], capture_output=True, text=True, check=False)
    staged = subprocess.run(["git", "diff", "--cached", "--no-color", "-U3"], capture_output=True, text=True, check=False)
    return (unstaged.stdout or "") + "\n" + (staged.stdout or "")


def audit_unified_diff(diff_text: str) -> list[Finding]:
    """Parse a unified diff string and return all slop/test-theater findings."""
    findings: list[Finding] = []
    current_file: str | None = None
    new_line_no = 0

    removed_assertions: dict[str, int] = {}
    added_assertions: dict[str, int] = {}
    consecutive_comment_code: list[tuple[int, str]] = []

    def flush_comment_block() -> None:
        if current_file and len(consecutive_comment_code) >= 3:
            first_line, first_text = consecutive_comment_code[0]
            findings.append(
                Finding(
                    severity="WARNING",
                    rule="commented-code-block",
                    file=current_file,
                    line=first_line,
                    message=f"{len(consecutive_comment_code)} consecutive lines of commented-out code added.",
                    snippet=first_text.strip(),
                )
            )
        consecutive_comment_code.clear()

    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            flush_comment_block()
            current_file = None
            new_line_no = 0
            continue

        if raw_line.startswith("+++ "):
            flush_comment_block()
            target = raw_line[4:].strip()
            if target == "/dev/null":
                current_file = None
            else:
                current_file = target[2:] if target.startswith("b/") else target
            continue

        if raw_line.startswith("--- "):
            continue

        hunk_match = hunk_re.match(raw_line)
        if hunk_match:
            flush_comment_block()
            new_line_no = int(hunk_match.group(1))
            continue

        if current_file is None:
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            content = raw_line[1:]
            if is_test_file(current_file) and ASSERTION_LINE_RE.search(content):
                removed_assertions[current_file] = removed_assertions.get(current_file, 0) + 1
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            content = raw_line[1:]
            line_no = new_line_no
            new_line_no += 1

            # Skip auditing audit_diff.py or test fixtures if self-referential? Keep general.
            test_file = is_test_file(current_file)

            if test_file:
                if ASSERTION_LINE_RE.search(content):
                    added_assertions[current_file] = added_assertions.get(current_file, 0) + 1
                if any(p.search(content) for p in SKIP_PATTERNS):
                    findings.append(
                        Finding(
                            severity="CRITICAL",
                            rule="test-skip",
                            file=current_file,
                            line=line_no,
                            message="Skipped or disabled test added.",
                            snippet=content.strip(),
                        )
                    )
                if any(p.search(content) for p in TRIVIAL_ASSERT_PATTERNS):
                    findings.append(
                        Finding(
                            severity="CRITICAL",
                            rule="trivial-assertion",
                            file=current_file,
                            line=line_no,
                            message="Trivial no-op assertion added (test theater).",
                            snippet=content.strip(),
                        )
                    )

            if any(p.search(content) for p in STUB_PATTERNS):
                findings.append(
                    Finding(
                        severity="CRITICAL",
                        rule="placeholder-stub",
                        file=current_file,
                        line=line_no,
                        message="Placeholder stub or TODO/FIXME marker added.",
                        snippet=content.strip(),
                    )
                )

            if any(p.search(content) for p in DEBUGGER_PATTERNS):
                findings.append(
                    Finding(
                        severity="CRITICAL",
                        rule="debugger-leftover",
                        file=current_file,
                        line=line_no,
                        message="Interactive debugger statement left in code.",
                        snippet=content.strip(),
                    )
                )

            if any(p.search(content) for p in SWALLOWED_ERROR_PATTERNS):
                findings.append(
                    Finding(
                        severity="WARNING",
                        rule="swallowed-error",
                        file=current_file,
                        line=line_no,
                        message="Exception caught and silently swallowed.",
                        snippet=content.strip(),
                    )
                )

            if any(p.search(content) for p in DEBUG_PRINT_PATTERNS):
                findings.append(
                    Finding(
                        severity="WARNING",
                        rule="debug-print",
                        file=current_file,
                        line=line_no,
                        message="Console debug statement added.",
                        snippet=content.strip(),
                    )
                )

            comment_match = COMMENT_LINE_RE.match(content)
            if comment_match and CODE_LIKE_RE.search(comment_match.group(2)):
                consecutive_comment_code.append((line_no, content))
            else:
                flush_comment_block()
            continue

        # Context line
        flush_comment_block()
        if not raw_line.startswith("\\"):
            new_line_no += 1

    flush_comment_block()

    for test_path, removed_count in removed_assertions.items():
        added_count = added_assertions.get(test_path, 0)
        if removed_count > added_count:
            findings.append(
                Finding(
                    severity="CRITICAL",
                    rule="removed-assertions",
                    file=test_path,
                    line=1,
                    message=(
                        f"Net loss of test assertions ({removed_count} removed vs {added_count} added). "
                        "Verify tests were not weakened to force a pass."
                    ),
                )
            )

    return findings


def format_human_report(findings: Iterable[Finding]) -> str:
    """Format findings into a readable terminal report."""
    items = list(findings)
    if not items:
        return "slop-guard: CLEAN (0 findings)."

    lines = [f"slop-guard: {len(items)} finding(s) detected:"]
    for item in items:
        loc = f"{item.file}:{item.line}"
        lines.append(f"  [{item.severity}] ({item.rule}) {loc} - {item.message}")
        if item.snippet:
            lines.append(f"      {item.snippet}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit git diff for AI slop and test theater.")
    parser.add_argument("--base", help="Git ref/branch to diff against (default: HEAD).")
    parser.add_argument("--diff-file", type=Path, help="Read unified diff from a file instead of git.")
    parser.add_argument("--json", action="store_true", help="Output findings as JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on WARNING findings too.")
    args = parser.parse_args(argv)

    try:
        if args.diff_file:
            diff_text = args.diff_file.read_text(encoding="utf-8")
        else:
            diff_text = _run_git_diff(args.base)
    except (OSError, RuntimeError) as exc:
        print(f"slop-guard error: {exc}", file=sys.stderr)
        return 2

    findings = audit_unified_diff(diff_text)
    critical_count = sum(1 for f in findings if f.severity == "CRITICAL")
    warning_count = sum(1 for f in findings if f.severity == "WARNING")

    if args.json:
        payload = {
            "clean": len(findings) == 0,
            "critical": critical_count,
            "warnings": warning_count,
            "findings": [asdict(f) for f in findings],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_human_report(findings))

    if critical_count > 0:
        return 1
    if args.strict and warning_count > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
