"""Unit tests for Swift language support in no-fake-done."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import audit_diff  # noqa: E402


class TestSwiftSupport(unittest.TestCase):
    """Verify Xcode/Swift Testing test-file detection, rules, and false-positive guards."""

    def test_xcode_and_swift_test_file_detection(self) -> None:
        self.assertTrue(audit_diff.is_test_file("MyAppTests/LoginTests.swift"))
        self.assertTrue(audit_diff.is_test_file("MyAppUITests/OnboardingUITests.swift"))
        self.assertTrue(audit_diff.is_test_file("Sources/Feature/AuthSpec.swift"))
        self.assertTrue(audit_diff.is_test_file("Tests/AppTests/BillingTests.swift"))
        self.assertFalse(audit_diff.is_test_file("Sources/App/AuthService.swift"))

    def test_catches_all_eight_swift_issues_in_diff(self) -> None:
        swift_diff = """diff --git a/MyAppTests/LoginTests.swift b/MyAppTests/LoginTests.swift
--- a/MyAppTests/LoginTests.swift
+++ b/MyAppTests/LoginTests.swift
@@ -1,6 +1,8 @@
 import XCTest
 final class LoginTests: XCTestCase {
     func testLogin() throws {
+        throw XCTSkip("flaky")
-        XCTAssertEqual(login("a", "b"), true)
-        XCTAssertNotNil(session)
+        XCTAssertTrue(true)
     }
 }
diff --git a/Sources/App/Auth.swift b/Sources/App/Auth.swift
--- a/Sources/App/Auth.swift
+++ b/Sources/App/Auth.swift
@@ -1,2 +1,10 @@
 struct Auth {
+    func refresh() { fatalError("Not implemented") }
+    func load() {
+        _ = try? fetch()
+        do { try save() } catch { }
+        // swiftlint:disable force_cast
+        print("debug")
+    }
 }
"""
        findings = audit_diff.audit_unified_diff(swift_diff)
        rules = [f.rule for f in findings]
        self.assertEqual(len(findings), 8, f"Expected 8 findings, got {findings}")
        self.assertIn("test-skip", rules)
        self.assertIn("trivial-assertion", rules)
        self.assertIn("removed-assertions", rules)
        self.assertIn("placeholder-stub", rules)
        self.assertIn("lint-type-suppression", rules)
        self.assertIn("debug-print", rules)
        self.assertEqual(rules.count("swallowed-error"), 2)

    def test_swift_testing_framework_macros_and_disabled_func(self) -> None:
        diff = """diff --git a/AppTests/CheckoutTests.swift b/AppTests/CheckoutTests.swift
--- a/AppTests/CheckoutTests.swift
+++ b/AppTests/CheckoutTests.swift
@@ -1,4 +1,9 @@
 import Testing
+@Test(.disabled("investigating"))
 func checkoutFlow() {
-    #expect(total == 42)
-    #require(receipt != nil)
+    #expect(true)
 }
+func disabled_testRefund() {}
"""
        findings = audit_diff.audit_unified_diff(diff)
        by_rule = [f.rule for f in findings]
        self.assertEqual(by_rule.count("test-skip"), 2)
        self.assertIn("trivial-assertion", by_rule)
        self.assertIn("removed-assertions", by_rule)

    def test_swift_force_try_flagged(self) -> None:
        diff = """diff --git a/Sources/Loader.swift b/Sources/Loader.swift
--- a/Sources/Loader.swift
+++ b/Sources/Loader.swift
@@ -1 +1,2 @@
 func load() {
+    let cfg = try! parseConfig()
 }
"""
        findings = audit_diff.audit_unified_diff(diff)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "swallowed-error")
        self.assertEqual(findings[0].severity, "WARNING")

    def test_false_positive_guards(self) -> None:
        diff = """diff --git a/Sources/ViewController.swift b/Sources/ViewController.swift
--- a/Sources/ViewController.swift
+++ b/Sources/ViewController.swift
@@ -1,2 +1,6 @@
 final class ViewController {
+    required init?(coder: NSCoder) {
+        fatalError("init(coder:) has not been implemented")
+    }
+    func decodeUser(data: Data) {
+        let user = try? JSONDecoder().decode(User.self, from: data)
+    }
 }
diff --git a/cli/tool.py b/cli/tool.py
--- a/cli/tool.py
+++ b/cli/tool.py
@@ -1 +1,2 @@
 def main():
+    print("ok")
"""
        findings = audit_diff.audit_unified_diff(diff)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
