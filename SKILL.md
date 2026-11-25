---
name: slop-guard
description: >-
  Pre-completion diff and test-integrity auditor for AI coding agents.
  Use before declaring any coding task complete, or when asked to audit
  AI-generated changes for placeholder stubs, weakened or skipped tests
  ("test theater"), debug leftovers, swallowed errors, and scope creep.
---

# Slop Guard

Run this skill **before** reporting that a coding task is complete. It pairs a
deterministic `git diff` audit script with a concise semantic checklist so
broken stubs, weakened tests, and unrequested edits never slip through.

---

## Workflow

### 1. Run the Deterministic Diff Audit

Run `scripts/audit_diff.py` from the repository root (works on Windows, macOS,
and Linux with Python 3.10+ and zero external dependencies):

```bash
python scripts/audit_diff.py
```

Useful options:
- `--base main` — compare against a base branch or commit instead of `HEAD`.
- `--json` — output structured JSON for automated parsing.
- `--strict` — exit non-zero on `WARNING` findings as well as `CRITICAL`.
- `--diff-file path/to/changes.diff` — audit a saved patch file.

### 2. Resolve All `CRITICAL` Findings

Do **not** report the task as complete while any `CRITICAL` finding remains:
- **Test Theater (`test-skip`, `trivial-assertion`, `removed-assertions`):**
  Restore deleted assertions, remove skip decorators, and replace trivial
  assertions with real behavioral checks.
- **Placeholder Stubs (`placeholder-stub`):**
  Implement the missing logic or remove dead `TODO`/`NotImplementedError` stubs.
- **Debug Leftovers (`debugger-leftover`):**
  Remove `breakpoint()`, `pdb.set_trace()`, and `debugger;` statements.

### 3. Review `WARNING` Findings & Semantic Checklist

Inspect any `WARNING` findings (`swallowed-error`, `debug-print`,
`commented-code-block`). Then read [references/checklist.md](references/checklist.md)
to verify what regex cannot catch:
- No "adding instead of replacing" compatibility/fallback layers.
- No partial ("80% done") implementations missing error paths.
- No unrequested refactors outside the task scope.

### 4. Final Verification

Re-run the project's test suite and `python scripts/audit_diff.py` after your
final edit. Report only observed test results and a clean audit.
