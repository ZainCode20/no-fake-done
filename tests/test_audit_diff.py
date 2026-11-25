"""Unit tests for no-fake-done's audit_diff.py."""

from __future__ import annotations

import json
import subprocess
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
    """Verify detection of test theater, stubs, secrets, swallowed errors, and CLI behavior."""

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

    def test_detects_stubs_debuggers_and_multiline_swallowed_errors(self) -> None:
        diff = """diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -1,2 +1,10 @@
 def process():
+    # TODO: implement validation
+    breakpoint()
+    try:
+        return 1
+    except Exception:
+        pass
"""
        findings = audit_diff.audit_unified_diff(diff)
        by_rule = {f.rule: f for f in findings}
        self.assertEqual(by_rule["placeholder-stub"].severity, "CRITICAL")
        self.assertEqual(by_rule["debugger-leftover"].severity, "CRITICAL")
        self.assertEqual(by_rule["swallowed-error"].severity, "WARNING")

    def test_detects_multiline_js_empty_catch_and_ts_ignore(self) -> None:
        diff = """diff --git a/src/client.ts b/src/client.ts
--- a/src/client.ts
+++ b/src/client.ts
@@ -1,2 +1,8 @@
+// @ts-ignore
+try {
+  run();
+} catch (err) {
+}
"""
        findings = audit_diff.audit_unified_diff(diff)
        by_rule = {f.rule: f for f in findings}
        self.assertEqual(by_rule["lint-type-suppression"].severity, "WARNING")
        self.assertEqual(by_rule["swallowed-error"].severity, "WARNING")

    def test_detects_hardcoded_secret_and_redacts_snippet(self) -> None:
        fake_key = "AKIA" + "1234567890ABCDEF"
        diff = f"""diff --git a/src/config.py b/src/config.py
--- a/src/config.py
+++ b/src/config.py
@@ -1 +1,2 @@
 ENV = "prod"
+AWS_KEY = "{fake_key}"
"""
        findings = audit_diff.audit_unified_diff(diff)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "hardcoded-secret")
        self.assertEqual(findings[0].severity, "CRITICAL")
        self.assertEqual(findings[0].snippet, "[REDACTED]")
        self.assertNotIn(fake_key, findings[0].snippet)

    def test_excludes_markdown_and_respects_inline_ignore(self) -> None:
        diff = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 # Docs
+TODO: add screenshots
diff --git a/src/cache.py b/src/cache.py
--- a/src/cache.py
+++ b/src/cache.py
@@ -1 +1,2 @@
 def get_key():
+    # TODO: intentional fixture  # no-fake-done: ignore
"""
        findings = audit_diff.audit_unified_diff(diff)
        self.assertEqual(findings, [])

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

    def test_scans_untracked_files_in_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "-C", str(repo), "init"], capture_output=True, check=True)
            (repo / "new_module.py").write_text("def run():\n    raise NotImplementedError()\n", encoding="utf-8")

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = audit_diff.main(["--repo", str(repo), "--json"])

            self.assertEqual(code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["critical"], 1)
            self.assertEqual(payload["findings"][0]["file"], "new_module.py")
            self.assertEqual(payload["findings"][0]["rule"], "placeholder-stub")

    def test_cli_exit_codes_strict_and_error(self) -> None:
        warn_diff = """diff --git a/src/app.js b/src/app.js
--- a/src/app.js
+++ b/src/app.js
@@ -1 +1,2 @@
 const x = 1;
+console.log(x);
"""
        with tempfile.TemporaryDirectory() as tmp:
            diff_path = Path(tmp) / "warn.diff"
            diff_path.write_text(warn_diff, encoding="utf-8")

            with patch("sys.stdout", StringIO()):
                self.assertEqual(audit_diff.main(["--diff-file", str(diff_path)]), 0)
                self.assertEqual(audit_diff.main(["--diff-file", str(diff_path), "--strict"]), 2)

            with patch("sys.stderr", StringIO()):
                self.assertEqual(audit_diff.main(["--diff-file", str(Path(tmp) / "missing.diff")]), 3)


if __name__ == "__main__":
    unittest.main()
