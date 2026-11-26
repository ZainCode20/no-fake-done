---
name: no-fake-done
description: >-
  Project and diff auditor for AI coding agents (Python, JS/TS, Swift, and more).
  Use before declaring any code-editing task complete, or when asked to audit a
  project, repository, or pull request for placeholder stubs, weakened or skipped
  tests ("test theater"), hardcoded secrets, swallowed errors, and linter/type
  suppressions. Do not activate for pure Q&A or documentation-only edits.
---

# No Fake Done

Pairs a deterministic code & diff auditor ([audit_diff.py](./scripts/audit_diff.py))
with a concise semantic checklist ([checklist.md](./references/checklist.md)) so
stubs, weakened tests, and hidden shortcuts never slip into a codebase or final
response.

---

## When to Use (and When Not to)

- **Use** when auditing an existing project/repository, reviewing a branch/PR,
  or finishing your own code-editing task.
- **Skip** for pure conceptual Q&A, read-only architecture explanations, or
  documentation-only edits (`.md`, `.txt`, `.rst` are excluded by default).

---

## Workflow

### 1. Pick the Right Scope & Run the Audit

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
- `--max-findings 50` — cap text output on large legacy repos (`0` = unlimited; `--json` always returns all).
- `--strict` — fail with exit code `2` on `WARNING` findings as well as `CRITICAL`.
- `--no-untracked` — skip scanning newly created untracked files.
- `--exclude "generated/*"` — exclude additional file globs (repeatable).
- `--diff-file path/to/changes.diff` — audit a saved unified patch.

Exit codes: `0` = clean, `1` = `CRITICAL` findings, `2` = `WARNING` with
`--strict`, `3` = git/IO error.

### 2. Resolve Every `CRITICAL` Finding

When finishing your own coding task, never declare victory while any `CRITICAL`
finding remains in your changes:
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

Inspect `WARNING` findings (`swallowed-error` including `except: pass`, empty
`catch {}`, discarded `try?`, and `try!`; `lint-type-suppression` including
`@ts-ignore`, `# type: ignore`, and `// swiftlint:disable`; `debug-print`; and
`commented-code-block`). If a line is genuinely intentional, add an inline
suppression with a reason:

```python
except KeyError:  # no-fake-done: ignore -- optional cache key
```

Then read [references/checklist.md](./references/checklist.md) to verify
architectural integrity that static pattern matching cannot catch.

### 4. Re-Run & Quote the Scope Summary

After your final edit:
1. Re-run the project's relevant test suite.
2. Re-run `audit_diff.py` (with `--changed` or `--base` for your own edits, or
   default `--all` for full-project audits).
3. Always quote the **scope summary** (e.g., `scanned 6 file(s) (+142 lines) [diff vs HEAD]`)
   alongside the observed test result so the user knows exactly what was checked.
