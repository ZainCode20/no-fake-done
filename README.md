# slop-guard

**Pre-completion diff & test-integrity auditor for AI coding agents.**

Stop AI coding assistants from declaring a task *"Done!"* when their `git diff` contains weakened/skipped tests (**"test theater"**), leftover `TODO` stubs, `NotImplementedError`, debuggers, or swallowed exceptions.

---

## What It Catches

| Severity | Rule | Examples |
| :--- | :--- | :--- |
| `CRITICAL` | `test-skip` | `@pytest.mark.skip`, `test.skip(`, `xit(`, `@Ignore`, `t.Skip(` |
| `CRITICAL` | `trivial-assertion` | `assert True`, `assert 1 == 1`, `expect(true).toBe(true)` |
| `CRITICAL` | `removed-assertions` | Net loss of `assert` / `expect(` lines in test files |
| `CRITICAL` | `placeholder-stub` | `TODO`, `FIXME`, `raise NotImplementedError`, `unimplemented!()` |
| `CRITICAL` | `debugger-leftover` | `breakpoint()`, `pdb.set_trace()`, `debugger;` |
| `WARNING` | `swallowed-error` | Bare `except:`, `except Exception: pass`, empty `catch {}` |
| `WARNING` | `debug-print` | `console.log(`, `console.debug(` |
| `WARNING` | `commented-code-block` | 3+ consecutive lines of commented-out code |

Plus a concise semantic checklist in [`references/checklist.md`](references/checklist.md) for catching *"adding instead of replacing"* workarounds and scope creep.

---

## Installation

### Antigravity
Copy or clone into your workspace `.agents/skills/slop-guard/` or global `~/.gemini/config/skills/slop-guard/`:
```bash
git clone https://github.com/ZainCode20/slop-guard.git ~/.gemini/config/skills/slop-guard
```

### Claude Code / Cursor / Codex
Copy the `slop-guard` folder into your project's `.claude/skills/slop-guard/` (or global `~/.claude/skills/slop-guard/`):
```bash
git clone https://github.com/ZainCode20/slop-guard.git .claude/skills/slop-guard
```

---

## Standalone CLI Usage

Requires **Python 3.10+** (zero external dependencies).

```bash
# Audit current changes against HEAD
python scripts/audit_diff.py

# Audit against a base branch
python scripts/audit_diff.py --base main

# Machine-readable JSON output
python scripts/audit_diff.py --json

# Fail on warnings too (great for CI)
python scripts/audit_diff.py --strict
```

---

## Running Tests

```bash
python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE)
