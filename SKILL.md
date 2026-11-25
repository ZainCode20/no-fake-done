---
name: no-fake-done
description: >-
  Pre-completion diff and test-integrity auditor for AI coding agents.
  Use before declaring any code-editing task complete, or when asked to audit
  AI-generated changes for placeholder stubs, weakened or skipped tests
  ("test theater"), hardcoded secrets, swallowed errors, type/lint suppressions,
  and scope creep. Do not activate for pure Q&A or documentation-only edits.
---

# No Fake Done

Run this skill **before** declaring a code-editing task complete. It pairs a
deterministic diff auditor ([audit_diff.py](./scripts/audit_diff.py)) with a
short semantic checklist ([checklist.md](./references/checklist.md)) so stubs,
weakened tests, and unrequested edits never slip into the final response.

---

## When to Use (and When Not to)

- **Use** after modifying or creating source/test files, right before running
  your final summary for the user.
- **Skip** for pure conceptual Q&A, read-only codebase research, or
  documentation-only edits (`.md`, `.txt`, `.rst` are excluded by default).

---

## Workflow

### 1. Run the Deterministic Diff Audit

Execute [audit_diff.py](./scripts/audit_diff.py) from the **skill directory**,
pointing `--repo` at the user's git repository (Python 3.10+, zero external
dependencies):

```bash
python <skill_dir>/scripts/audit_diff.py --repo <project_root> --json
```

Useful flags:
- `--base main` — audit against a base branch or commit instead of `HEAD`.
- `--strict` — fail with exit code `2` on `WARNING` findings as well as `CRITICAL`.
- `--no-untracked` — skip scanning newly created untracked files.
- `--exclude "generated/*"` — exclude additional file globs (repeatable).
- `--diff-file path/to/changes.diff` — audit a saved unified patch.

Exit codes: `0` = clean, `1` = `CRITICAL` findings, `2` = `WARNING` with
`--strict`, `3` = git/IO error.

### 2. Resolve Every `CRITICAL` Finding

Never report a task as complete while any `CRITICAL` finding remains:
- **Test Theater (`test-skip`, `trivial-assertion`, `removed-assertions`):**
  Restore deleted assertions, remove skip decorators, and replace tautologies
  (`assert True`, `expect(true).toBe(true)`) with real behavioral checks.
- **Placeholder Stubs (`placeholder-stub`):**
  Implement the missing logic or remove dead `TODO`/`FIXME`/`NotImplementedError`.
- **Hardcoded Secrets (`hardcoded-secret`):**
  Remove credentials/keys immediately and load them from environment variables.
- **Debug Leftovers (`debugger-leftover`):**
  Remove `breakpoint()`, `pdb.set_trace()`, and `debugger;`.

### 3. Review `WARNING` Findings & Semantic Checklist

Inspect all `WARNING` findings (`swallowed-error`, `lint-type-suppression`,
`debug-print`, `commented-code-block`). Fix unintentional issues; if a line is
genuinely intentional (e.g., an intentional empty catch or fixture), append an
inline suppression with a reason:

```python
except KeyError:  # no-fake-done: ignore -- optional cache key
```

Then read [references/checklist.md](./references/checklist.md) to verify
architectural integrity that regex cannot catch.

### 4. Re-Run & Report

After your final edit:
1. Re-run the project's relevant test suite.
2. Re-run `audit_diff.py` and confirm exit code `0` (`CLEAN`).
3. Include a brief **Verification** line in your final reply stating both the
   observed test result and `no-fake-done: CLEAN`.
