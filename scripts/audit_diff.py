#!/usr/bin/env python3
"""Deterministic git diff auditor for catching AI coding slop before completion.

Exit codes:
    0: Clean (no critical findings; warnings allowed unless --strict)
    1: Critical findings detected
    2: Warning findings detected with --strict
    3: Execution or git error
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_EXCLUDED_GLOBS = (
    "*.md",
    "*.mdx",
    "*.rst",
    "*.txt",
    "*.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Cargo.lock",
    "*.min.js",
    "*.min.css",
    "*.svg",
    "*.snap",
)

TEST_FILE_RE = re.compile(
    r"(^|[\\/])(tests?|__tests__|spec)[\\/]|"
    r"(^|[\\/])test_[^\\/]+\.[a-zA-Z0-9]+$|"
    r"(_test|\.test|\.spec)\.[a-zA-Z0-9]+$",
    re.IGNORECASE,
)

INLINE_IGNORE_RE = re.compile(r"slop-guard:\s*ignore\b", re.IGNORECASE)

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

SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN\s+(RSA|EC|OPENSSH|DSA|PRIVATE)\s+PRIVATE\s+KEY-----"),
]

SWALLOWED_ERROR_INLINE_PATTERNS = [
    re.compile(r"^\s*except\s*:\s*(pass|\.\.\.)\s*(#.*)?$"),
    re.compile(r"^\s*except\s+Exception(\s+as\s+\w+)?\s*:\s*(pass|\.\.\.)\s*(#.*)?$"),
    re.compile(r"\bcatch\s*(\([^)]*\))?\s*\{\s*\}"),
]

PY_EXCEPT_HEADER_RE = re.compile(r"^\s*except(\s+Exception(\s+as\s+\w+)?)?\s*:\s*(#.*)?$")
PY_PASS_ONLY_RE = re.compile(r"^\s*(pass|\.\.\.)\s*(#.*)?$")
JS_CATCH_OPEN_RE = re.compile(r"\bcatch\s*(\([^)]*\))?\s*\{\s*$")
JS_CLOSE_BRACE_RE = re.compile(r"^\s*\}\s*$")

LINT_TYPE_SUPPRESSION_PATTERNS = [
    re.compile(r"@ts-ignore\b"),
    re.compile(r"@ts-nocheck\b"),
    re.compile(r"\beslint-disable\b"),
    re.compile(r"#\s*type:\s*ignore\s*$"),
]

DEBUG_PRINT_PATTERNS = [
    re.compile(r"\bconsole\.(log|debug)\s*\("),
]

COMMENT_LINE_RE = re.compile(r"^\s*(#|//)\s*(.+)$")
CODE_LIKE_RE = re.compile(r"(=|\(|\)|\{|\}|;|\b(def|class|function|return|import|const|let|var)\b)")

MAX_UNTRACKED_BYTES = 256 * 1024


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


def is_excluded(filepath: str, exclude_globs: Iterable[str]) -> bool:
    """Return True if filepath matches any exclusion glob."""
    normalized = filepath.replace("\\", "/")
    basename = Path(normalized).name
    for pattern in exclude_globs:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
    return False


def _run_git(args: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _synthesize_untracked_diff(repo: Path) -> str:
    """Build synthetic unified diffs for untracked, non-ignored text files."""
    listed = _run_git(["ls-files", "--others", "--exclude-standard"], repo)
    if listed.returncode != 0 or not listed.stdout.strip():
        return ""

    chunks: list[str] = []
    for rel_path in listed.stdout.splitlines():
        rel_path = rel_path.strip()
        if not rel_path:
            continue
        full_path = repo / rel_path
        if not full_path.is_file():
            continue
        try:
            if full_path.stat().st_size > MAX_UNTRACKED_BYTES:
                continue
            raw = full_path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if not lines:
            continue
        chunks.append(f"diff --git a/{rel_path} b/{rel_path}")
        chunks.append("--- /dev/null")
        chunks.append(f"+++ b/{rel_path}")
        chunks.append(f"@@ -0,0 +1,{len(lines)} @@")
        chunks.extend(f"+{line}" for line in lines)
    return "\n".join(chunks)


def _run_git_diff(base: str | None, repo: Path, include_untracked: bool = True) -> str:
    """Collect unified diff from git (against base ref, HEAD, or working tree)."""
    check_repo = _run_git(["rev-parse", "--is-inside-work-tree"], repo)
    if check_repo.returncode != 0:
        raise RuntimeError(check_repo.stderr.strip() or f"Not a git repository: {repo}")

    if base:
        proc = _run_git(["diff", "--no-color", "-U3", base], repo)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"git diff failed for base '{base}'")
        diff_text = proc.stdout
    else:
        has_head = _run_git(["rev-parse", "--verify", "HEAD"], repo).returncode == 0
        if has_head:
            proc = _run_git(["diff", "--no-color", "-U3", "HEAD"], repo)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "git diff HEAD failed")
            diff_text = proc.stdout
        else:
            unstaged = _run_git(["diff", "--no-color", "-U3"], repo)
            staged = _run_git(["diff", "--cached", "--no-color", "-U3"], repo)
            diff_text = (unstaged.stdout or "") + "\n" + (staged.stdout or "")

    if include_untracked:
        untracked = _synthesize_untracked_diff(repo)
        if untracked:
            diff_text = f"{diff_text}\n{untracked}" if diff_text else untracked

    return diff_text


def audit_unified_diff(
    diff_text: str,
    exclude_globs: Iterable[str] = DEFAULT_EXCLUDED_GLOBS,
) -> list[Finding]:
    """Parse a unified diff string and return all slop/test-theater findings."""
    findings: list[Finding] = []
    current_file: str | None = None
    skip_current_file = False
    new_line_no = 0

    removed_assertions: dict[str, int] = {}
    added_assertions: dict[str, int] = {}
    consecutive_comment_code: list[tuple[int, str]] = []
    pending_py_except: tuple[int, str] | None = None
    pending_js_catch: tuple[int, str] | None = None

    def flush_comment_block() -> None:
        if current_file and not skip_current_file and len(consecutive_comment_code) >= 3:
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

    def reset_multiline_state() -> None:
        nonlocal pending_py_except, pending_js_catch
        pending_py_except = None
        pending_js_catch = None

    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            flush_comment_block()
            reset_multiline_state()
            current_file = None
            skip_current_file = False
            new_line_no = 0
            continue

        if raw_line.startswith("+++ "):
            flush_comment_block()
            reset_multiline_state()
            target = raw_line[4:].strip()
            if target == "/dev/null":
                current_file = None
                skip_current_file = True
            else:
                current_file = target[2:] if target.startswith("b/") else target
                skip_current_file = is_excluded(current_file, exclude_globs)
            continue

        if raw_line.startswith("--- "):
            continue

        hunk_match = hunk_re.match(raw_line)
        if hunk_match:
            flush_comment_block()
            reset_multiline_state()
            new_line_no = int(hunk_match.group(1))
            continue

        if current_file is None or skip_current_file:
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

            if INLINE_IGNORE_RE.search(content):
                flush_comment_block()
                reset_multiline_state()
                continue

            # Check multi-line swallowed exceptions before resetting state
            if pending_py_except is not None:
                if PY_PASS_ONLY_RE.match(content):
                    ex_line, ex_snippet = pending_py_except
                    findings.append(
                        Finding(
                            severity="WARNING",
                            rule="swallowed-error",
                            file=current_file,
                            line=ex_line,
                            message="Multi-line exception caught and silently swallowed.",
                            snippet=f"{ex_snippet.strip()} {content.strip()}",
                        )
                    )
                pending_py_except = None

            if pending_js_catch is not None:
                if JS_CLOSE_BRACE_RE.match(content):
                    c_line, c_snippet = pending_js_catch
                    findings.append(
                        Finding(
                            severity="WARNING",
                            rule="swallowed-error",
                            file=current_file,
                            line=c_line,
                            message="Empty multi-line catch block swallows errors.",
                            snippet=f"{c_snippet.strip()} }}",
                        )
                    )
                pending_js_catch = None

            if PY_EXCEPT_HEADER_RE.match(content):
                pending_py_except = (line_no, content)
            elif JS_CATCH_OPEN_RE.search(content):
                pending_js_catch = (line_no, content)

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

            if any(p.search(content) for p in SECRET_PATTERNS):
                findings.append(
                    Finding(
                        severity="CRITICAL",
                        rule="hardcoded-secret",
                        file=current_file,
                        line=line_no,
                        message="Possible hardcoded credential or private key detected.",
                        snippet="[REDACTED]",
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

            if any(p.search(content) for p in SWALLOWED_ERROR_INLINE_PATTERNS):
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

            if any(p.search(content) for p in LINT_TYPE_SUPPRESSION_PATTERNS):
                findings.append(
                    Finding(
                        severity="WARNING",
                        rule="lint-type-suppression",
                        file=current_file,
                        line=line_no,
                        message="Type-checker or linter suppression added without justification.",
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
        reset_multiline_state()
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
    parser.add_argument("--repo", type=Path, default=Path("."), help="Path to git repository (default: current directory).")
    parser.add_argument("--base", help="Git ref/branch to diff against (default: HEAD).")
    parser.add_argument("--diff-file", type=Path, help="Read unified diff from a file instead of git.")
    parser.add_argument("--no-untracked", action="store_true", help="Skip scanning untracked new files.")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional file glob to exclude (repeatable).",
    )
    parser.add_argument("--json", action="store_true", help="Output findings as JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit with code 2 on WARNING findings too.")
    args = parser.parse_args(argv)

    exclude_globs = (*DEFAULT_EXCLUDED_GLOBS, *args.exclude)

    try:
        if args.diff_file:
            diff_text = args.diff_file.read_text(encoding="utf-8")
        else:
            diff_text = _run_git_diff(
                base=args.base,
                repo=args.repo,
                include_untracked=not args.no_untracked,
            )
    except (OSError, RuntimeError) as exc:
        print(f"slop-guard error: {exc}", file=sys.stderr)
        return 3

    findings = audit_unified_diff(diff_text, exclude_globs=exclude_globs)
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
