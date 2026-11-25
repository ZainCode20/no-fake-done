# no-fake-done

[![CI](https://github.com/ZainCode20/no-fake-done/actions/workflows/ci.yml/badge.svg)](https://github.com/ZainCode20/no-fake-done/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)

**Pre-completion diff & test-integrity auditor skill for AI coding agents.**

Stop AI coding assistants from declaring a task *"Done!"* when their changes contain weakened or skipped tests (**"test theater"**), leftover `TODO` / `NotImplementedError` stubs, hardcoded secrets, swallowed exceptions, or `@ts-ignore` / `# type: ignore` shortcuts.

---

## What It Catches

| Severity | Rule | Examples |
| :--- | :--- | :--- |
| `CRITICAL` | `test-skip` | `@pytest.mark.skip`, `test.skip(`, `xit(`, `@Ignore`, `t.Skip(` |
| `CRITICAL` | `trivial-assertion` | `assert True`, `assert 1 == 1`, `expect(true).toBe(true)` |
| `CRITICAL` | `removed-assertions` | Net loss of `assert` / `expect(` lines in test files |
| `CRITICAL` | `placeholder-stub` | `TODO`, `FIXME`, `raise NotImplementedError`, `unimplemented!()` |
| `CRITICAL` | `hardcoded-secret` | AWS keys (`AKIA...`), GitHub tokens (`ghp_...`), API keys (`sk-...`), private keys *(redacted in output)* |
| `CRITICAL` | `debugger-leftover` | `breakpoint()`, `pdb.set_trace()`, `debugger;` |
| `WARNING` | `swallowed-error` | Single-line & multi-line `except Exception: pass`, empty `catch {}` |
| `WARNING` | `lint-type-suppression` | `@ts-ignore`, `@ts-nocheck`, `eslint-disable`, bare `# type: ignore` |
| `WARNING` | `debug-print` | `console.log(`, `console.debug(` |
| `WARNING` | `commented-code-block` | 3+ consecutive lines of commented-out code |

- **Scans untracked new files** automatically (so brand-new AI files with stubs/skips don't slip past `git diff`).
- **Skips docs & lockfiles** (`.md`, `.txt`, `package-lock.json`, `pnpm-lock.yaml`, etc.) by default to avoid false positives.
- **Inline escape hatch:** add `# no-fake-done: ignore` (or `// no-fake-done: ignore`) on intentionally excluded lines.
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

> **How the Stop Hook works:** When an agent finishes a turn, [`scripts/hook_stop.py`](scripts/hook_stop.py) audits the workspace's `git diff` (and untracked new files). If any `CRITICAL` issue is found, it blocks completion once and sends the exact findings back to the agent so it fixes them automatically. Non-git folders, clean diffs, and already-continued turns pass through silently.

---

## Standalone CLI Usage

Requires **Python 3.10+** (zero external dependencies).

```bash
# Audit current repo changes (tracked + untracked) against HEAD
python scripts/audit_diff.py --repo /path/to/project

# Audit against a base branch
python scripts/audit_diff.py --base main

# Machine-readable JSON output
python scripts/audit_diff.py --json

# Fail on warnings too (exit code 2)
python scripts/audit_diff.py --strict

# Exclude custom paths
python scripts/audit_diff.py --exclude "generated/*" --exclude "fixtures/*"
```

### Exit Codes
- `0` — Clean (no `CRITICAL` findings)
- `1` — One or more `CRITICAL` findings detected
- `2` — `WARNING` findings detected with `--strict`
- `3` — Git or I/O error

---

## Running Tests

```bash
python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE)
