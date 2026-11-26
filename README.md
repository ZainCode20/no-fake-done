# no-fake-done

[![CI](https://github.com/ZainCode20/no-fake-done/actions/workflows/ci.yml/badge.svg)](https://github.com/ZainCode20/no-fake-done/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)

**Project & diff auditor skill + automatic Stop hook for AI coding agents.**

Stop AI coding assistants from claiming *"Done!"* when a codebase or diff contains skipped/weakened tests (**"test theater"**), empty stub functions, leftover `TODO` / `NotImplementedError` / `fatalError` stubs, hardcoded secrets, swallowed errors, or `@ts-ignore` / `swiftlint:disable` shortcuts.

![no-fake-done terminal demo](assets/demo.svg)

---

## Supported Languages

| Language / Ecosystem | Test Theater (`test-skip`, `trivial-assertion`, `removed-assertions`) | Stubs, Errors, Suppressions & Debug Noise |
| :--- | :--- | :--- |
| **Python** | `@pytest.mark.skip`, `@unittest.skip`, `assert True`, `assert 1 == 1`, net-removed `assert*` | `TODO`/`FIXME`, `raise NotImplementedError`, single & multi-line `except: pass`, bare `# type: ignore`, `breakpoint()`, `pdb.set_trace()` |
| **JavaScript / TypeScript** | `test.skip(`, `it.skip(`, `xit(`, `expect(true).toBe(true)`, net-removed `expect`/`assert` | `TODO`/`FIXME`, `throw new Error("not implemented")`, single & multi-line empty `catch {}`, `@ts-ignore`, `@ts-nocheck`, `eslint-disable`, `debugger;`, `console.log(` |
| **Swift (XCTest & Swift Testing)** | `FooTests.swift` / `MyAppTests/` detection, `throw XCTSkip(`, `XCTSkipIf`/`Unless`, `@Test(.disabled)`, `func disabled_test…`, `XCTAssertTrue(true)`, `#expect(true)`, net-removed `XCTAssert*` / `#expect` | `TODO`/`FIXME`, `fatalError("…not implemented…")` *(exempts `init(coder:)`)*, empty `catch {}`, discarded `try?`, `try!`, `// swiftlint:disable`, `// swiftformat:disable`, `print(` / `debugPrint(` / `dump(` |
| **Go / Rust / JVM (Generic)** | `@Ignore`, `t.Skip(`, `FooTest.kt`/`.java`/`.cs` assertion loss | `TODO`/`FIXME`, `todo!()`, `unimplemented!()`, hardcoded secrets (`AKIA…`, `ghp_…`, `sk-…`, private keys), commented-out code blocks |

---

## What It Catches

| Severity | Rule | Examples |
| :--- | :--- | :--- |
| `CRITICAL` | `test-skip` | `@pytest.mark.skip`, `test.skip(`, `xit(`, `throw XCTSkip(`, `@Test(.disabled)`, `@Ignore`, `t.Skip(` |
| `CRITICAL` | `trivial-assertion` | `assert True`, `expect(true).toBe(true)`, `XCTAssertTrue(true)`, `#expect(true)` |
| `CRITICAL` | `removed-assertions` | Net loss of `assert` / `expect(` / `XCTAssert*` / `#expect(` lines in test files *(diff modes)* |
| `CRITICAL` | `empty-test` | Python AST: `def test_*(): pass` / `...` with zero assertions |
| `CRITICAL` | `empty-stub-func` | Python AST: function/method body is only `pass` or `...` *(exempts `@abstractmethod`, `@overload`, `Protocol`/`ABC`)* |
| `CRITICAL` | `placeholder-stub` | `TODO`, `FIXME`, `raise NotImplementedError`, `fatalError("Not implemented")`, `unimplemented!()` |
| `CRITICAL` | `hardcoded-secret` | AWS keys (`AKIA...`), GitHub tokens (`ghp_...`), API keys (`sk-...`), private keys *(redacted in output)* |
| `CRITICAL` | `debugger-leftover` | `breakpoint()`, `pdb.set_trace()`, `debugger;` |
| `WARNING` | `swallowed-error` | `except Exception: pass`, empty `catch {}`, Swift discarded `try?` and `try!` |
| `WARNING` | `lint-type-suppression` | `@ts-ignore`, `@ts-nocheck`, `eslint-disable`, bare `# type: ignore`, `// swiftlint:disable` |
| `WARNING` | `debug-print` | `console.log(`, `console.debug(`, Swift `print(` / `debugPrint(` / `dump(` |
| `WARNING` | `commented-code-block` | 3+ consecutive lines of commented-out code |

- **Full-project scan by default** (works on committed repos and plain non-git folders alike), plus `--changed` and `--base main` for targeted diff checks.
- **5-Angle Verification Protocol:** pairs static diff checks with [`references/verification-angles.md`](references/verification-angles.md) so agents also verify **build/typecheck**, **automated tests**, **runtime happy + edge-case smoke tests**, and **git scope** before claiming "Done!".
- **Audit Only vs. Audit & Fix:** Ask your agent *"Run `no-fake-done` on this repo"* for a read-only audit, or *"Run `no-fake-done` and fix all findings"* to have the agent resolve every issue and re-verify until clean.
- **Skips docs, lockfiles & vendor dirs** (`.md`, `.txt`, `Pods/`, `DerivedData/`, `.build/`, `node_modules/`, lockfiles, etc.) automatically.
- **Inline escape hatch & rule muting:** add `# no-fake-done: ignore` on intentional lines, or pass `--ignore-rule swallowed-error` to mute a specific rule.
- **Semantic checklist:** pairs with [`references/checklist.md`](references/checklist.md) for catching *"adding instead of replacing"* workarounds and scope creep.

---

## Installation

### Claude Code (1-Command Plugin + Automatic Stop Hook)
Install directly via the Claude Code plugin marketplace—this activates both the `no-fake-done` skill and the automatic **Stop hook** (`hooks/hooks.json`):
```bash
/plugin marketplace add ZainCode20/no-fake-done
/plugin install no-fake-done
```

### Antigravity (Plugin + Automatic Stop Hook)
Clone into your workspace `.agents/plugins/no-fake-done/` or global `~/.gemini/config/plugins/no-fake-done/` (includes `plugin.json` and `hooks.json`):
```bash
git clone https://github.com/ZainCode20/no-fake-done.git ~/.gemini/config/plugins/no-fake-done
```

### Skill-Only Install (Cursor / Codex / Manual)
If you only want the `SKILL.md` workflow without the automatic Stop hook:
```bash
git clone https://github.com/ZainCode20/no-fake-done.git .claude/skills/no-fake-done
```

> **How the Stop Hook works:** When an agent finishes a turn, [`scripts/hook_stop.py`](scripts/hook_stop.py) audits **only uncommitted + untracked edits** (`--changed` scope) so legacy `TODO`s in existing repos never block your session. If a `CRITICAL` issue was just introduced, it blocks completion once and feeds the exact findings back to the agent.

---

## Standalone CLI Usage

Requires **Python 3.10+** (zero external dependencies).

```bash
# Scan the entire project (default — all tracked + untracked files, or plain folder)
python scripts/audit_diff.py --repo /path/to/project

# Audit only uncommitted + untracked changes vs HEAD
python scripts/audit_diff.py --repo /path/to/project --changed

# Audit a branch / PR against main (recommended for CI)
python scripts/audit_diff.py --base main

# Machine-readable JSON output (includes scope metadata)
python scripts/audit_diff.py --json

# Fail on warnings too (exit code 2)
python scripts/audit_diff.py --strict

# Exclude custom paths, mute a rule, or show unlimited findings
python scripts/audit_diff.py --exclude "generated/*" --ignore-rule swallowed-error --max-findings 0
```

### Exit Codes
- `0` — Clean (no `CRITICAL` findings)
- `1` — One or more `CRITICAL` findings detected
- `2` — `WARNING` findings detected with `--strict`
- `3` — Git, config, or I/O error

---

## Per-Repo Configuration (`.nofakedone.json`)

Drop an optional `.nofakedone.json` in your repository root (honored by both the CLI and the automatic Stop hook):

```json
{
  "exclude": ["generated/*", "fixtures/*"],
  "ignore_rules": ["debug-print"],
  "severities": {
    "swallowed-error": "CRITICAL"
  },
  "max_findings": 50,
  "strict": false
}
```

CLI flags (`--exclude`, `--ignore-rule`, `--strict`, `--max-findings`, `--config <path>`) merge with or override `.nofakedone.json`.

---

## FAQ

**How do I audit only my uncommitted changes instead of the whole project?**
By default, running `audit_diff.py` scans **the entire project** (`--all`) and prints an explicit file/line count on every run. Pass `--changed` to audit only uncommitted changes vs `HEAD` (which is what the automatic Stop hook uses), or `--base main` for a branch/PR diff.

---

## Running Tests

```bash
python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE)
