# Example: Catching AI Slop Before Reporting "Done"

## Scenario
An AI agent is asked to fix a discount calculation bug and ensure tests pass.
Before responding to the user, the agent runs `no-fake-done`:

```bash
python scripts/audit_diff.py
```

## Bad Diff Output
```text
no-fake-done: 3 finding(s) detected:
  [CRITICAL] (test-skip) tests/test_billing.py:18 - Skipped or disabled test added.
      @pytest.mark.skip(reason="flaky after refactor")
  [CRITICAL] (placeholder-stub) src/billing.py:42 - Placeholder stub or TODO/FIXME marker added.
      # TODO: handle negative coupon edge case
  [WARNING] (swallowed-error) src/billing.py:49 - Exception caught and silently swallowed.
      except Exception: pass
```

## Resolution
Instead of claiming *"All tests pass!"*, the agent:
1. Removes `@pytest.mark.skip` and fixes the underlying assertion in `tests/test_billing.py`.
2. Implements the negative-coupon validation in `src/billing.py` and removes the `TODO`.
3. Replaces `except Exception: pass` with explicit `ValueError` handling.
4. Re-runs `python scripts/audit_diff.py` -> `no-fake-done: CLEAN (0 findings).`
