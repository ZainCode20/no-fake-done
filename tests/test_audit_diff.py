"""Unit tests for slop-guard's audit_diff.py."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import audit_diff  # noqa: E402


class TestAuditDiff(unittest.TestCase):
    """Verify detection of test theater, stubs, debuggers, and clean diffs."""

    def test_clean_diff_returns_zero_findings(self) -> None:
        diff = """diff --git a/src/math_utils.py b/src/math_utils.py
--- a/src/math_utils.py
+++ b/src/math_utils.py
@@ -1,3 +1,5 @@
 def add(a: int, b: int) -> int:
     return a + b
+
+def subtract(a: int, b: int) -> int:
+    return a - b
diff --git a/tests/test_math_utils.py b/tests/test_math_utils.py
--- a/tests/test_math_utils.py
+++ b/tests/test_math_utils.py
@@ -1,3 +1,5 @@
 from src.math_utils import add, subtract
 def test_add():
     assert add(1, 2) == 3
+def test_subtract():
+    assert subtract(5, 3) == 2
"""
        findings = audit_diff.audit_unified_diff(diff)
        self.assertEqual(findings, [])

    def test_detects_test_skip_and_trivial_assertion(self) -> None:
        diff = """diff --git a/tests/test_auth.py b/tests/test_auth.py
--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -10,3 +10,6 @@
+@pytest.mark.skip(reason="fix later")
 def test_login():
-    assert login("user", "pass") is True
+    assert True
"""
        findings = audit_diff.audit_unified_diff(diff)
        rules = {f.rule for f in findings}
        self.assertIn("test-skip", rules)
        self.assertIn("trivial-assertion", rules)
        self.assertTrue(all(f.severity == "CRITICAL" for f in findings))

    def test_detects_removed_assertions_net_loss(self) -> None:
        diff = """diff --git a/tests/billing.test.ts b/tests/billing.test.ts
--- a/tests/billing.test.ts
+++ b/tests/billing.test.ts
@@ -5,4 +5,2 @@
 test("charges card", () => {
-  expect(result.status).toBe("paid");
-  expect(result.amount).toBe(100);
 });
"""
        findings = audit_diff.audit_unified_diff(diff)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "removed-assertions")
        self.assertEqual(findings[0].severity, "CRITICAL")

    def test_detects_stubs_debuggers_and_swallowed_errors(self) -> None:
        diff = """diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -1,2 +1,9 @@
 def process():
+    # TODO: implement validation
+    breakpoint()
+    try:
+        return 1
+    except Exception: pass
"""
        findings = audit_diff.audit_unified_diff(diff)
        by_rule = {f.rule: f for f in findings}
        self.assertEqual(by_rule["placeholder-stub"].severity, "CRITICAL")
        self.assertEqual(by_rule["debugger-leftover"].severity, "CRITICAL")
        self.assertEqual(by_rule["swallowed-error"].severity, "WARNING")

    def test_detects_commented_out_code_block(self) -> None:
        diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,6 @@
+# def legacy_handler(req):
+#     val = req.get("id")
+#     return val
 def new_handler():
     return 1
"""
        findings = audit_diff.audit_unified_diff(diff)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "commented-code-block")
        self.assertEqual(findings[0].severity, "WARNING")

    def test_cli_json_and_exit_codes(self) -> None:
        bad_diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
 x = 1
+# TODO: finish this
"""
        with tempfile.TemporaryDirectory() as tmp:
            diff_path = Path(tmp) / "bad.diff"
            diff_path.write_text(bad_diff, encoding="utf-8")

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = audit_diff.main(["--diff-file", str(diff_path), "--json"])

            self.assertEqual(code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["clean"])
            self.assertEqual(payload["critical"], 1)
            self.assertEqual(payload["findings"][0]["rule"], "placeholder-stub")


if __name__ == "__main__":
    unittest.main()
