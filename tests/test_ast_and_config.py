"""Unit tests for Python AST analysis and .nofakedone.json configuration."""

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
import hook_stop  # noqa: E402


class TestPythonAstAndConfig(unittest.TestCase):
    """Verify AST empty-stub/empty-test detection, exemptions, and .nofakedone.json."""

    def test_ast_detects_empty_stub_and_empty_test(self) -> None:
        src = (
            "def refund(order_id: str) -> bool:\n"
            '    """Process refund."""\n'
            "    pass\n\n"
            "async def sync() -> None:\n"
            "    ...\n"
        )
        findings = audit_diff.audit_python_ast(src, "src/billing.py")
        self.assertEqual([f.rule for f in findings], ["empty-stub-func", "empty-stub-func"])

        test_src = "def test_checkout():\n    pass\n"
        test_findings = audit_diff.audit_python_ast(test_src, "tests/test_checkout.py")
        self.assertEqual(len(test_findings), 1)
        self.assertEqual(test_findings[0].rule, "empty-test")
        self.assertEqual(test_findings[0].severity, "CRITICAL")

    def test_ast_exempts_protocols_abstractmethods_overloads_and_inline_ignore(self) -> None:
        src = (
            "from abc import ABC, abstractmethod\n"
            "from typing import Protocol, overload\n\n"
            "class Store(Protocol):\n"
            "    def get(self, key: str) -> str:\n"
            "        ...\n\n"
            "class BaseHandler(ABC):\n"
            "    @abstractmethod\n"
            "    def handle(self) -> None:\n"
            "        pass\n\n"
            "@overload\n"
            "def parse(x: int) -> int:\n"
            "    ...\n\n"
            "def intentional_noop() -> None:  # no-fake-done: ignore\n"
            "    pass\n"
        )
        findings = audit_diff.audit_python_ast(src, "src/interfaces.py")
        self.assertEqual(findings, [])

    def test_repo_config_exclude_ignore_and_severity_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "generated").mkdir()
            (root / "generated" / "gen.py").write_text("# TODO: generated\n", encoding="utf-8")
            (root / "app.js").write_text("try { run(); } catch (e) {}\nconsole.log('x');\n", encoding="utf-8")
            (root / ".nofakedone.json").write_text(
                json.dumps(
                    {
                        "exclude": ["generated/*"],
                        "ignore_rules": ["debug-print"],
                        "severities": {"swallowed-error": "CRITICAL"},
                    }
                ),
                encoding="utf-8",
            )

            out = StringIO()
            with patch("sys.stdout", out):
                code = audit_diff.main(["--repo", tmp, "--json"])

            self.assertEqual(code, 1)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["critical"], 1)
            self.assertEqual(payload["warnings"], 0)
            self.assertEqual(payload["findings"][0]["rule"], "swallowed-error")
            self.assertEqual(payload["findings"][0]["severity"], "CRITICAL")

    def test_invalid_config_exits_with_code_3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".nofakedone.json").write_text("{bad json", encoding="utf-8")
            with patch("sys.stderr", StringIO()):
                self.assertEqual(audit_diff.main(["--repo", tmp]), 3)

    def test_stop_hook_uses_ast_and_repo_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "-C", tmp, "init"], capture_output=True, check=True)
            (repo / "stub.py").write_text("def unfinished():\n    pass\n", encoding="utf-8")

            res = hook_stop.evaluate_stop_hook(
                {"cwd": tmp, "terminationReason": "NO_TOOL_CALL", "continuationActive": False},
                mode="antigravity",
            )
            self.assertEqual(res["decision"], "continue")
            self.assertIn("empty-stub-func", res["reason"])

            # Now ignore empty-stub-func via .nofakedone.json -> Stop hook allows completion
            (repo / ".nofakedone.json").write_text(
                json.dumps({"ignore_rules": ["empty-stub-func"]}),
                encoding="utf-8",
            )
            res_ignored = hook_stop.evaluate_stop_hook(
                {"cwd": tmp, "terminationReason": "NO_TOOL_CALL", "continuationActive": False},
                mode="antigravity",
            )
            self.assertEqual(res_ignored, {})


if __name__ == "__main__":
    unittest.main()
