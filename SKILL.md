---
name: no-fake-done
description: >-
  Multi-angle project & diff auditor for AI coding agents (Python, JS/TS, Swift,
  and more). Use before declaring any code-editing task complete, or when asked
  to audit, verify, or fix an app/repository for skipped tests ("test theater"),
  placeholder stubs, hardcoded secrets, swallowed errors, build/runtime failures,
  and scope creep. Do not activate for pure Q&A or documentation-only edits.
---

# No Fake Done

Pairs a deterministic code & diff auditor ([audit_diff.py](./scripts/audit_diff.py))
with a **5-Angle Verification Protocol** ([verification-angles.md](./references/verification-angles.md))
and semantic checklist ([checklist.md](./references/checklist.md)) so AI agents
verify an app thoroughly—and resolve real issues—before saying "Done!".

---

## Modes: Audit Only vs. Audit & Fix

- **Audit Only** *(when the user asks to "check", "audit", or "review" a repo)*:
  Run the audit + applicable verification angles and report findings **without**
  editing the user's code unless asked.
- **Audit & Fix** *(when finishing your own coding task, or when the user asks
  to "audit and fix" / "make sure this app is fine")*:
  Fix every `CRITICAL` finding (and any actionable `WARNING`s or failing checks),
  then re-run until clean.

---

## Workflow

### 1. Pick the Right Scope & Run the Static Audit

Execute [audit_diff.py](./scripts/audit_diff.py) pointing `--repo` at the target
project (Python 3.10+, zero external dependencies):

| Scenario | Command |
| :--- | :--- |
| **User asks to audit/check a project or repo** *(default)* | `python <skill_dir>/scripts/audit_diff.py --repo <project_root>` |
| **Finishing your own uncommitted coding task** | `python <skill_dir>/scripts/audit_diff.py --repo <project_root> --changed` |
| **Auditing a branch / PR (or after committing along the way)** | `python <skill_dir>/scripts/audit_diff.py --repo <project_root> --base main` |

Additional flags:
- `--all` — explicit alias for the default full-project scan (works on plain non-git folders too).
- `--json` — structured JSON output including a `scope` summary (`mode`, `files_scanned`, `lines_scanned`).
- `--ignore-rule swallowed-error` — mute a specific rule (repeatable; useful under `--strict`).
- `--config path/to/.nofakedone.json` — load a custom config file (otherwise `<repo>/.nofakedone.json` is auto-loaded if present).
- `--max-findings 50` — cap text output on large legacy repos (`0` = unlimited; `--json` always returns all).
- `--strict` — fail with exit code `2` on `WARNING` findings as well as `CRITICAL`.
- `--no-untracked` — skip scanning newly created untracked files.
- `--exclude "generated/*"` — exclude additional file globs (repeatable).
- `--diff-file path/to/changes.diff` — audit a saved unified patch.

Exit codes: `0` = clean, `1` = `CRITICAL` findings, `2` = `WARNING` with
`--strict`, `3` = git/IO error.

### 2. Resolve Every `CRITICAL` Finding (in Audit & Fix Mode)

Never report a task as complete while any `CRITICAL` finding remains in your changes:
- **Test Theater (`test-skip`, `trivial-assertion`, `removed-assertions`):**
  Restore deleted assertions, remove skip markers (`@pytest.mark.skip`,
  `test.skip`, `throw XCTSkip`, `@Test(.disabled)`), and replace tautologies
  (`assert True`, `expect(true).toBe(true)`, `XCTAssertTrue(true)`, `#expect(true)`)
  with real behavioral assertions.
- **Placeholder Stubs (`placeholder-stub`):**
  Implement missing logic or remove dead `TODO`/`FIXME`/`NotImplementedError`/
  `fatalError("Not implemented")` stubs.
- **Hardcoded Secrets (`hardcoded-secret`):**
  Remove credentials/keys immediately and load them from environment variables.
- **Debug Leftovers (`debugger-leftover`):**
  Remove `breakpoint()`, `pdb.set_trace()`, and `debugger;`.

### 3. Review `WARNING` Findings & Semantic Checklist

Inspect `WARNING` findings (`swallowed-error`, `lint-type-suppression`,
`debug-print`, `commented-code-block`). If a line is genuinely intentional, add
an inline suppression with a reason:

```python
except KeyError:  # no-fake-done: ignore -- optional cache key
```

Read [references/checklist.md](./references/checklist.md) for architectural drift
checks ("adding instead of replacing", "80% complete" traps).

### 4. Verify from All 5 Angles & Report Honestly

Before concluding, follow [references/verification-angles.md](./references/verification-angles.md)
to test the app from multiple angles:
1. **Static Audit:** Re-run `audit_diff.py` after the final edit and quote the
   exact scope summary (`scanned N file(s) (+M lines)`).
2. **Build / Typecheck:** Verify compilation/types (or report OS/SDK blockers honestly).
3. **Automated Tests:** Run the real test suite after the final edit.
4. **Runtime Smoke Test:** Execute the app/CLI with both a valid happy-path input
   and an invalid/edge-case input.
5. **Scope & Git Status:** Confirm `git diff --stat` has no unintended changes.
