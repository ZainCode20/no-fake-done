#!/usr/bin/env python3
"""Deterministic code & git diff auditor for catching AI coding slop.

Modes:
    Default / --all : Scan every tracked + untracked source file in the project
                      (also works on plain non-git folders).
    --changed       : Scan only uncommitted + untracked changes vs HEAD.
    --base <ref>    : Scan changes since a branch or commit (e.g. --base main).
    --diff-file <f> : Scan a saved unified diff / patch file.

Exit codes:
    0: Clean (no critical findings; warnings allowed unless --strict)
    1: Critical findings detected
    2: Warning findings detected with --strict
    3: Execution or git error
"""

from __future__ import annotations

import argparse
import ast
import collections
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

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
    "Podfile.lock",
    "Package.resolved",
    "*.min.js",
    "*.min.css",
    "*.svg",
    "*.snap",
    "*.pbxproj",
    "*.storyboard",
    "*.xib",
    ".git/*",
    "Pods/*",
    "Carthage/*",
    ".build/*",
    "DerivedData/*",
    "*.xcodeproj/*",
    "*.xcworkspace/*",
    "node_modules/*",
    "vendor/*",
    "dist/*",
    "build/*",
    ".venv/*",
    "venv/*",
    "__pycache__/*",
)

TEST_FILE_RE = re.compile(
    r"(^|[\\/])(tests?|__tests__|spec)[\\/]|"
    r"(^|[\\/])test_[^\\/]+\.[a-zA-Z0-9]+$|"
    r"(_test|\.test|\.spec)\.[a-zA-Z0-9]+$",
    re.IGNORECASE,
)

# Case-sensitive CamelCase test naming used by Xcode/Swift, Kotlin, Java, C#, Obj-C.
XCODE_TEST_RE = re.compile(
    r"(^|[\\/])\w*(Tests|UITests)[\\/]|"
    r"(^|[\\/])\w+(Tests?|Spec)\.(swift|kt|java|cs|m)$"
)

INLINE_IGNORE_RE = re.compile(r"(no-fake-done|slop-guard):\s*ignore\b", re.IGNORECASE)

SKIP_PATTERNS = [
    re.compile(r"@pytest\.mark\.skip\b"),
    re.compile(r"@unittest\.skip\b"),
    re.compile(r"\b(test|it|describe)\.skip\s*\("),
    re.compile(r"\bx(it|describe|test)\s*\("),
    re.compile(r"@Ignore\b"),
    re.compile(r"\bt\.Skip\s*\("),
]

SWIFT_SKIP_PATTERNS = [
    re.compile(r"\bthrow\s+XCTSkip\s*\("),
    re.compile(r"\bXCTSkip(If|Unless)\s*\("),
    re.compile(r"@(Test|Suite)\s*\([^)]*\.disabled\b"),
    re.compile(r"\bfunc\s+(x|_|disabled_?|DISABLED_?)test\w*\s*\("),
]

TRIVIAL_ASSERT_PATTERNS = [
    re.compile(r"^\s*assert\s+True\s*(#.*)?$"),
    re.compile(r"^\s*assert\s+1\s*==\s*1\s*(#.*)?$"),
    re.compile(r"^\s*expect\s*\(\s*true\s*\)\s*\.\s*toBe\s*\(\s*true\s*\)"),
    re.compile(r"^\s*expect\s*\(\s*1\s*\)\s*\.\s*toBe\s*\(\s*1\s*\)"),
]

SWIFT_TRIVIAL_ASSERT_PATTERNS = [
    re.compile(r"\bXCTAssertTrue\s*\(\s*true\b"),
    re.compile(r"\bXCTAssert\s*\(\s*true\b"),
    re.compile(r"\bXCTAssertFalse\s*\(\s*false\b"),
    re.compile(r"\bXCTAssertEqual\s*\(\s*1\s*,\s*1\b"),
    re.compile(r"#expect\s*\(\s*true\s*\)"),
]

ASSERTION_LINE_RE = re.compile(
    r"\b(assert\w*|expect|should|require)\b\s*[\(\.]|"
    r"\bassert\s+|"
    r"\bXCT(Assert\w*|Fail)\s*\(|"
    r"#(expect|require)\s*\(",
    re.IGNORECASE,
)

STUB_PATTERNS = [
    re.compile(r"\b(TODO|FIXME|XXX|HACK)\b\s*:?"),
    re.compile(r"\braise\s+NotImplementedError\b"),
    re.compile(r"\bthrow\s+new\s+Error\s*\(\s*['\"]not implemented['\"]", re.IGNORECASE),
    re.compile(r"\b(unimplemented|todo)!\s*\("),
]

SWIFT_STUB_PATTERNS = [
    re.compile(
        r"\b(fatalError|preconditionFailure)\s*\(\s*\"[^\"]*"
        r"(not\s+implemented|unimplemented|todo|fixme)[^\"]*\"\s*\)",
        re.IGNORECASE,
    ),
]

# Standard Xcode storyboard/NSCoding boilerplate that is legitimate in UIKit/AppKit.
SWIFT_INIT_CODER_RE = re.compile(r"init\(coder:\)\s+has\s+not\s+been\s+implemented", re.IGNORECASE)

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

SWIFT_DISCARDED_TRY_RE = re.compile(r"^\s*(?:_\s*=\s*)?try\?\s+\S")
SWIFT_FORCE_TRY_RE = re.compile(r"\btry!\s+\S")

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

SWIFT_SUPPRESSION_PATTERNS = [
    re.compile(r"//\s*swiftlint:disable\b"),
    re.compile(r"//\s*swiftformat:disable\b"),
]

DEBUG_PRINT_PATTERNS = [
    re.compile(r"\bconsole\.(log|debug)\s*\("),
]

SWIFT_DEBUG_PRINT_RE = re.compile(r"(?<!\.)\b(print|debugPrint|dump)\s*\(")

COMMENT_LINE_RE = re.compile(r"^\s*(#|//)\s*(.+)$")
CODE_LIKE_RE = re.compile(
    r"(=|\(|\)|\{|\}|;|\b(def|class|function|func|struct|return|import|const|let|var)\b)"
)

MAX_FILE_BYTES = 256 * 1024
MAX_UNTRACKED_BYTES = MAX_FILE_BYTES
DEFAULT_MAX_FINDINGS = 50
CONFIG_FILENAME = ".nofakedone.json"
VALID_SEVERITIES = {"CRITICAL", "WARNING"}


def load_repo_config(repo: Path, config_path: Path | None = None) -> dict[str, Any]:
    """Load optional .nofakedone.json configuration from repo root or explicit path."""
    target = config_path if config_path is not None else (repo / CONFIG_FILENAME)
    if not target.is_file():
        if config_path is not None:
            raise RuntimeError(f"Config file not found: {target}")
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid config in {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Config in {target} must be a JSON object.")
    return data


def _is_stub_only_body(body: list[ast.stmt]) -> bool:
    """Return True if a function body contains only docstring + pass / Ellipsis (...)."""
    stmts = list(body)
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(stmts[0].value, ast.Constant)
        and isinstance(stmts[0].value.value, str)
    ):
        stmts = stmts[1:]
    if not stmts:
        return False
    for stmt in stmts:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            continue
        return False
    return True


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            names.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.add(dec.attr)
    return names


def _is_protocol_or_abc_class(cls_node: ast.ClassDef) -> bool:
    for base in cls_node.bases:
        if isinstance(base, ast.Name) and base.id in {"Protocol", "ABC"}:
            return True
        if isinstance(base, ast.Attribute) and base.attr in {"Protocol", "ABC"}:
            return True
    return False


def audit_python_ast(
    source: str,
    filepath: str,
    changed_lines: set[int] | None = None,
) -> list[Finding]:
    """Run zero-dependency Python AST checks for empty stub functions and empty tests."""
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return []

    raw_lines = source.splitlines()
    findings: list[Finding] = []
    test_file = is_test_file(filepath)

    def line_ignored(lineno: int, end_lineno: int | None) -> bool:
        hi = min(len(raw_lines), (end_lineno or lineno))
        for idx in range(max(1, lineno), hi + 1):
            if INLINE_IGNORE_RE.search(raw_lines[idx - 1]):
                return True
        return False

    def visit_block(stmts: list[ast.stmt], inside_protocol: bool = False) -> None:
        for node in stmts:
            if isinstance(node, ast.ClassDef):
                is_proto = inside_protocol or _is_protocol_or_abc_class(node)
                visit_block(node.body, inside_protocol=is_proto)
                continue

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, "end_lineno", node.lineno)
                if changed_lines is not None:
                    touched = any(ln in changed_lines for ln in range(node.lineno, (end_line or node.lineno) + 1))
                    if not touched:
                        continue

                if line_ignored(node.lineno, end_line):
                    continue

                decs = _decorator_names(node)
                if inside_protocol or decs.intersection({"abstractmethod", "overload"}):
                    continue

                if _is_stub_only_body(node.body):
                    snippet = raw_lines[node.lineno - 1].strip() if 1 <= node.lineno <= len(raw_lines) else ""
                    if test_file and node.name.startswith("test"):
                        findings.append(
                            Finding(
                                severity="CRITICAL",
                                rule="empty-test",
                                file=filepath,
                                line=node.lineno,
                                message=f"Empty test function '{node.name}' has no assertions (test theater).",
                                snippet=snippet,
                            )
                        )
                    else:
                        findings.append(
                            Finding(
                                severity="CRITICAL",
                                rule="empty-stub-func",
                                file=filepath,
                                line=node.lineno,
                                message=f"Function '{node.name}' body is an empty pass/... stub.",
                                snippet=snippet,
                            )
                        )

    visit_block(tree.body)
    return findings


def _collect_added_python_lines(diff_text: str, exclude_globs: Iterable[str]) -> dict[str, set[int]]:
    """Extract added line numbers per .py file from a unified diff for targeted AST checks."""
    py_lines: dict[str, set[int]] = {}
    current_file: str | None = None
    skip = False
    new_line_no = 0
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_file = None
            skip = False
            new_line_no = 0
            continue
        if raw_line.startswith("+++ "):
            target = raw_line[4:].strip()
            if target == "/dev/null":
                current_file = None
                skip = True
            else:
                current_file = target[2:] if target.startswith("b/") else target
                skip = language_of(current_file) != "python" or is_excluded(current_file, exclude_globs)
            continue
        if raw_line.startswith("--- "):
            continue
        hunk_match = hunk_re.match(raw_line)
        if hunk_match:
            new_line_no = int(hunk_match.group(1))
            continue
        if current_file is None or skip:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            py_lines.setdefault(current_file, set()).add(new_line_no)
            new_line_no += 1
        elif not raw_line.startswith("-") and not raw_line.startswith("\\"):
            new_line_no += 1
    return py_lines


def audit_python_files_in_repo(
    repo: Path,
    diff_text: str,
    exclude_globs: Iterable[str],
    full_scan: bool,
) -> list[Finding]:
    """Run AST checks on scanned Python files present in repo."""
    py_lines = _collect_added_python_lines(diff_text, exclude_globs)
    ast_findings: list[Finding] = []
    for rel_path, lines in py_lines.items():
        full_path = repo / rel_path
        if not full_path.is_file():
            continue
        try:
            if full_path.stat().st_size > MAX_FILE_BYTES:
                continue
            source = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ast_findings.extend(
            audit_python_ast(source, rel_path, changed_lines=None if full_scan else lines)
        )
    return ast_findings


def apply_config_rules(
    findings: list[Finding],
    ignored_rules: set[str],
    severity_overrides: dict[str, str],
) -> list[Finding]:
    """Filter ignored rules and apply optional severity overrides."""
    result: list[Finding] = []
    for f in findings:
        key = f.rule.lower()
        if key in ignored_rules:
            continue
        override = severity_overrides.get(key)
        if override in VALID_SEVERITIES:
            result.append(
                Finding(
                    severity=override,
                    rule=f.rule,
                    file=f.file,
                    line=f.line,
                    message=f.message,
                    snippet=f.snippet,
                )
            )
        else:
            result.append(f)
    return result


@dataclass
class Finding:
    """Single audit finding detected in a unified diff or full scan."""

    severity: str  # "CRITICAL" | "WARNING"
    rule: str
    file: str
    line: int
    message: str
    snippet: str = ""


@dataclass
class ScanScope:
    """Metadata describing what was audited."""

    mode: str  # "all" | "diff" | "base" | "diff-file"
    base: str | None
    files_scanned: int
    lines_scanned: int


def language_of(filepath: str) -> str:
    """Return canonical language key from file extension."""
    ext = Path(filepath).suffix.lower()
    if ext == ".swift":
        return "swift"
    if ext == ".py":
        return "python"
    if ext in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return "js"
    return ""


def is_test_file(filepath: str) -> bool:
    """Return True if the file path matches common or Xcode/JVM test conventions."""
    return bool(TEST_FILE_RE.search(filepath) or XCODE_TEST_RE.search(filepath))


def is_excluded(filepath: str, exclude_globs: Iterable[str]) -> bool:
    """Return True if filepath matches any exclusion glob (supports nested dir/* globs)."""
    normalized = filepath.replace("\\", "/").lstrip("./")
    parts = normalized.split("/")
    basename = parts[-1] if parts else normalized
    dir_parts = parts[:-1]

    for pattern in exclude_globs:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
        if pattern.endswith("/*"):
            dir_pat = pattern[:-2]
            if any(fnmatch.fnmatch(part, dir_pat) for part in dir_parts):
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


def _synthesize_added_diff_for_paths(
    repo: Path,
    rel_paths: Iterable[str],
    exclude_globs: Iterable[str] = (),
) -> str:
    """Build synthetic unified diffs treating every eligible text file as newly added."""
    chunks: list[str] = []
    seen: set[str] = set()

    for raw_rel in rel_paths:
        rel_path = raw_rel.strip().replace("\\", "/")
        if not rel_path or rel_path in seen:
            continue
        seen.add(rel_path)

        if exclude_globs and is_excluded(rel_path, exclude_globs):
            continue

        full_path = repo / rel_path
        if not full_path.is_file():
            continue
        try:
            if full_path.stat().st_size > MAX_FILE_BYTES:
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


def _synthesize_untracked_diff(repo: Path) -> str:
    """Build synthetic unified diffs for untracked, non-ignored text files."""
    listed = _run_git(["ls-files", "--others", "--exclude-standard"], repo)
    if listed.returncode != 0 or not listed.stdout.strip():
        return ""
    return _synthesize_added_diff_for_paths(repo, listed.stdout.splitlines())


def _walk_plain_directory(root: Path, exclude_globs: Iterable[str]) -> list[str]:
    """Collect relative file paths when scanning a folder that is not a git repository."""
    if not root.is_dir():
        raise RuntimeError(f"Directory does not exist: {root}")

    rel_paths: list[str] = []
    for current_root, dirs, files in os.walk(root):
        rel_dir = Path(current_root).relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""

        # Prune excluded directories in-place for speed.
        kept_dirs: list[str] = []
        for d in dirs:
            candidate = f"{rel_dir}/{d}/x" if rel_dir else f"{d}/x"
            if not is_excluded(candidate, exclude_globs):
                kept_dirs.append(d)
        dirs[:] = kept_dirs

        for fname in files:
            rel_file = f"{rel_dir}/{fname}" if rel_dir else fname
            if not is_excluded(rel_file, exclude_globs):
                rel_paths.append(rel_file)

    rel_paths.sort()
    return rel_paths


def _run_full_project_scan(
    repo: Path,
    include_untracked: bool = True,
    exclude_globs: Iterable[str] = DEFAULT_EXCLUDED_GLOBS,
) -> str:
    """Synthesize a full-project diff across all tracked + untracked files (or plain dir)."""
    if not repo.exists():
        raise RuntimeError(f"Path does not exist: {repo}")

    is_git = _run_git(["rev-parse", "--is-inside-work-tree"], repo).returncode == 0
    if is_git:
        tracked = _run_git(["ls-files"], repo)
        if tracked.returncode != 0:
            raise RuntimeError(tracked.stderr.strip() or "git ls-files failed")
        paths = tracked.stdout.splitlines()
        if include_untracked:
            untracked = _run_git(["ls-files", "--others", "--exclude-standard"], repo)
            if untracked.returncode == 0:
                paths.extend(untracked.stdout.splitlines())
    else:
        paths = _walk_plain_directory(repo, exclude_globs)

    return _synthesize_added_diff_for_paths(repo, paths, exclude_globs=exclude_globs)


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


def audit_diff_with_stats(
    diff_text: str,
    exclude_globs: Iterable[str] = DEFAULT_EXCLUDED_GLOBS,
) -> tuple[list[Finding], int, int]:
    """Parse a unified diff string and return (findings, files_scanned, lines_scanned)."""
    findings: list[Finding] = []
    current_file: str | None = None
    current_lang = ""
    skip_current_file = False
    new_line_no = 0

    scanned_files: set[str] = set()
    lines_scanned = 0

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
            current_lang = ""
            skip_current_file = False
            new_line_no = 0
            continue

        if raw_line.startswith("+++ "):
            flush_comment_block()
            reset_multiline_state()
            target = raw_line[4:].strip()
            if target == "/dev/null":
                current_file = None
                current_lang = ""
                skip_current_file = True
            else:
                current_file = target[2:] if target.startswith("b/") else target
                current_lang = language_of(current_file)
                skip_current_file = is_excluded(current_file, exclude_globs)
                if not skip_current_file:
                    scanned_files.add(current_file)
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
            lines_scanned += 1

            if INLINE_IGNORE_RE.search(content):
                flush_comment_block()
                reset_multiline_state()
                continue

            is_swift = current_lang == "swift"

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

                skip_hit = any(p.search(content) for p in SKIP_PATTERNS) or (
                    is_swift and any(p.search(content) for p in SWIFT_SKIP_PATTERNS)
                )
                if skip_hit:
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

                trivial_hit = any(p.search(content) for p in TRIVIAL_ASSERT_PATTERNS) or (
                    is_swift and any(p.search(content) for p in SWIFT_TRIVIAL_ASSERT_PATTERNS)
                )
                if trivial_hit:
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

            if not (is_swift and SWIFT_INIT_CODER_RE.search(content)):
                stub_hit = any(p.search(content) for p in STUB_PATTERNS) or (
                    is_swift and any(p.search(content) for p in SWIFT_STUB_PATTERNS)
                )
                if stub_hit:
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

            swallowed_inline = any(p.search(content) for p in SWALLOWED_ERROR_INLINE_PATTERNS)
            swift_discarded_try = is_swift and bool(SWIFT_DISCARDED_TRY_RE.search(content))
            swift_force_try = is_swift and bool(SWIFT_FORCE_TRY_RE.search(content))
            if swallowed_inline or swift_discarded_try or swift_force_try:
                if swift_force_try and not swallowed_inline:
                    msg = "Force-try (try!) crashes at runtime on error instead of handling it."
                elif swift_discarded_try and not swallowed_inline:
                    msg = "Discarded try? silently drops thrown errors."
                else:
                    msg = "Exception caught and silently swallowed."
                findings.append(
                    Finding(
                        severity="WARNING",
                        rule="swallowed-error",
                        file=current_file,
                        line=line_no,
                        message=msg,
                        snippet=content.strip(),
                    )
                )

            suppression_hit = any(p.search(content) for p in LINT_TYPE_SUPPRESSION_PATTERNS) or (
                is_swift and any(p.search(content) for p in SWIFT_SUPPRESSION_PATTERNS)
            )
            if suppression_hit:
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

            debug_print_hit = any(p.search(content) for p in DEBUG_PRINT_PATTERNS) or (
                is_swift and bool(SWIFT_DEBUG_PRINT_RE.search(content))
            )
            if debug_print_hit:
                findings.append(
                    Finding(
                        severity="WARNING",
                        rule="debug-print",
                        file=current_file,
                        line=line_no,
                        message="Debug print statement added.",
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

    return findings, len(scanned_files), lines_scanned


def audit_unified_diff(
    diff_text: str,
    exclude_globs: Iterable[str] = DEFAULT_EXCLUDED_GLOBS,
) -> list[Finding]:
    """Parse a unified diff string and return all findings."""
    findings, _, _ = audit_diff_with_stats(diff_text, exclude_globs=exclude_globs)
    return findings


def _scope_label(scope: ScanScope) -> str:
    if scope.mode == "all":
        return "full project scan"
    if scope.mode == "diff":
        return f"diff vs {scope.base or 'HEAD'}"
    if scope.mode == "base":
        return f"diff vs {scope.base}"
    return "diff file"


def format_human_report(
    findings: Iterable[Finding],
    scope: ScanScope | None = None,
    max_findings: int = DEFAULT_MAX_FINDINGS,
) -> str:
    """Format findings and scan scope into a readable terminal report."""
    items = list(findings)

    if not items:
        if scope is None:
            return "no-fake-done: CLEAN (0 findings)."
        if scope.files_scanned == 0:
            if scope.mode == "diff":
                return (
                    f"no-fake-done: nothing to audit — no uncommitted changes vs {scope.base or 'HEAD'}.\n"
                    "  Tip: run without --changed (or pass --all) to scan the whole project, "
                    "or --base main to audit a branch."
                )
            if scope.mode == "base":
                return f"no-fake-done: nothing to audit — no changes vs {scope.base}."
            return "no-fake-done: nothing to audit — 0 eligible source files found."
        return (
            f"no-fake-done: CLEAN — scanned {scope.files_scanned} file(s) "
            f"(+{scope.lines_scanned} lines) [{_scope_label(scope)}]."
        )

    ordered = sorted(items, key=lambda f: 0 if f.severity == "CRITICAL" else 1)
    counts = collections.Counter(f.rule for f in ordered)
    summary_str = ", ".join(f"{rule}: {count}" for rule, count in counts.most_common())

    if scope is not None:
        header = (
            f"no-fake-done: {len(ordered)} finding(s) across {scope.files_scanned} file(s) "
            f"[{_scope_label(scope)}]:"
        )
    else:
        header = f"no-fake-done: {len(ordered)} finding(s) detected:"

    lines = [header, f"  Summary: {summary_str}"]
    shown = ordered if max_findings <= 0 else ordered[:max_findings]
    for item in shown:
        loc = f"{item.file}:{item.line}"
        lines.append(f"  [{item.severity}] ({item.rule}) {loc} - {item.message}")
        if item.snippet:
            lines.append(f"      {item.snippet}")

    if max_findings > 0 and len(ordered) > max_findings:
        omitted = len(ordered) - max_findings
        lines.append(
            f"  ... and {omitted} more finding(s) omitted "
            "(pass --max-findings 0 or --json to see all)."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit source files or git diffs for AI slop and test theater."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Path to project or git repository (default: current directory).",
    )
    scope_group = parser.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--all",
        action="store_true",
        help="Scan all tracked and untracked project files (default when no scope flag is set).",
    )
    scope_group.add_argument(
        "--changed",
        action="store_true",
        help="Scan only uncommitted and untracked changes vs HEAD.",
    )
    scope_group.add_argument(
        "--base",
        help="Git ref/branch to diff against (e.g. --base main).",
    )
    scope_group.add_argument(
        "--diff-file",
        type=Path,
        help="Read unified diff from a file instead of scanning a repo.",
    )
    parser.add_argument(
        "--no-untracked",
        action="store_true",
        help="Skip scanning untracked new files.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional file glob to exclude (repeatable).",
    )
    parser.add_argument(
        "--ignore-rule",
        action="append",
        default=[],
        help="Rule name to ignore, e.g. swallowed-error or debug-print (repeatable).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=f"Path to JSON config file (default: <repo>/{CONFIG_FILENAME} if present).",
    )
    parser.add_argument(
        "--max-findings",
        type=int,
        default=None,
        help=f"Max findings printed in text output (default: {DEFAULT_MAX_FINDINGS}; 0 = unlimited).",
    )
    parser.add_argument("--json", action="store_true", help="Output findings as JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit with code 2 on WARNING findings too.")
    args = parser.parse_args(argv)

    try:
        config = load_repo_config(args.repo, config_path=args.config)
    except RuntimeError as exc:
        print(f"no-fake-done error: {exc}", file=sys.stderr)
        return 3

    cfg_excludes = [str(p) for p in config.get("exclude", []) if isinstance(p, str)]
    cfg_ignored = {str(r).strip().lower() for r in config.get("ignore_rules", []) if str(r).strip()}
    cfg_severities = {
        str(k).strip().lower(): str(v).strip().upper()
        for k, v in config.get("severities", {}).items()
        if isinstance(k, str) and isinstance(v, str)
    } if isinstance(config.get("severities"), dict) else {}

    max_findings = (
        args.max_findings
        if args.max_findings is not None
        else int(config.get("max_findings", DEFAULT_MAX_FINDINGS))
    )
    strict_mode = bool(args.strict or config.get("strict", False))
    exclude_globs = (*DEFAULT_EXCLUDED_GLOBS, *cfg_excludes, *args.exclude)

    try:
        if args.diff_file:
            mode = "diff-file"
            base_ref = None
            diff_text = args.diff_file.read_text(encoding="utf-8")
        elif args.base:
            mode = "base"
            base_ref = args.base
            diff_text = _run_git_diff(
                base=args.base,
                repo=args.repo,
                include_untracked=not args.no_untracked,
            )
        elif args.changed:
            mode = "diff"
            base_ref = "HEAD"
            diff_text = _run_git_diff(
                base=None,
                repo=args.repo,
                include_untracked=not args.no_untracked,
            )
        else:
            mode = "all"
            base_ref = None
            diff_text = _run_full_project_scan(
                repo=args.repo,
                include_untracked=not args.no_untracked,
                exclude_globs=exclude_globs,
            )
    except (OSError, RuntimeError) as exc:
        print(f"no-fake-done error: {exc}", file=sys.stderr)
        return 3

    findings, files_scanned, lines_scanned = audit_diff_with_stats(
        diff_text, exclude_globs=exclude_globs
    )
    if not args.diff_file:
        findings.extend(
            audit_python_files_in_repo(
                repo=args.repo,
                diff_text=diff_text,
                exclude_globs=exclude_globs,
                full_scan=(mode == "all"),
            )
        )

    ignored_rules = cfg_ignored | {r.strip().lower() for r in args.ignore_rule if r.strip()}
    findings = apply_config_rules(findings, ignored_rules=ignored_rules, severity_overrides=cfg_severities)
    scope = ScanScope(
        mode=mode,
        base=base_ref,
        files_scanned=files_scanned,
        lines_scanned=lines_scanned,
    )
    critical_count = sum(1 for f in findings if f.severity == "CRITICAL")
    warning_count = sum(1 for f in findings if f.severity == "WARNING")

    if args.json:
        payload = {
            "clean": len(findings) == 0,
            "critical": critical_count,
            "warnings": warning_count,
            "scope": asdict(scope),
            "findings": [asdict(f) for f in findings],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_human_report(findings, scope=scope, max_findings=max_findings))

    if critical_count > 0:
        return 1
    if strict_mode and warning_count > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
