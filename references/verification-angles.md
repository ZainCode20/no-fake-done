# 5-Angle App & Project Verification Protocol

Passing a regex diff check is only **one** angle. Before claiming an app, tool,
or feature is genuinely "done", verify it from all 5 angles that apply to the
project:

## Angle 1 — Static Slop & Test-Integrity Gate
Run `audit_diff.py` (with `--changed` for your edits, `--base main` for a PR,
or default `--all` for a whole-project audit).
- **Pass:** `0 CRITICAL` findings, all unintended `WARNING`s cleaned up.

## Angle 2 — Build, Compile & Typecheck
Verify the project actually compiles and typechecks cleanly using its native
toolchain:
- **Python:** `python -m py_compile ...`, `mypy` / `pyright` / `ruff` (if configured)
- **JS/TS:** `npm run build`, `npx tsc --noEmit`
- **Swift:** `swift build` (or `xcodebuild` on macOS)
- **Go / Rust:** `go vet ./...`, `cargo check`
- **Honesty rule:** If the target SDK is unavailable on the current OS (e.g.
  iOS `UIKit` on Linux/WSL), report `BLOCKED (OS/SDK)` explicitly—never claim
  a build passed when it couldn't run.

## Angle 3 — Automated Test Suite (Happy + Edge Cases)
Run the real test suite (`pytest`, `unittest`, `npm test`, `swift test`,
`go test`, `cargo test`) **after** your very last edit.
- Confirm both existing tests (no regressions) and new tests covering the fix.

## Angle 4 — Runtime & Adversarial Smoke Test
Execute the actual app, CLI, or endpoint—don't rely on unit tests alone:
- **Happy path:** Run a realistic valid input and inspect the real output.
- **Bad / edge-case input:** Test missing files, empty input, invalid flags,
  or malformed data—confirm it fails gracefully with a clear error instead of
  an unhandled crash or silent wrong answer.
- **UI / Web apps:** Verify the page loads with zero console/network errors
  and key user flows work end-to-end.

## Angle 5 — Regression, Scope & Side-Effect Check
- Run `git diff --stat` and confirm only intended files were modified.
- Verify no leftover temp files, debug artifacts, or accidental dependency
  changes remain in `git status`.

---

## Final Verification Report Format
Report each angle honestly in one compact table or bullet list:
- **Static Audit:** `no-fake-done: CLEAN` *(+ files/lines scanned)*
- **Build / Typecheck:** `PASS` / `FAIL` / `SKIPPED (reason)`
- **Tests:** `X/X passed` *(exact command run)*
- **Runtime Smoke Test:** `PASS` *(happy + edge case tested)*
- **Scope / Git Status:** `CLEAN` *(only intended files touched)*
