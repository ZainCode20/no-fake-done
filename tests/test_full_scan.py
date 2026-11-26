"""Unit tests for default full-project scan, --changed mode, scope metadata, and caps."""

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


class TestFullScanAndScope(unittest.TestCase):
    """Verify full-project default scan, --changed hint, plain folders, vendor exclusions, and Stop hook."""

    def test_committed_slop_found_by_default_and_clean_with_changed_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "-C", tmp, "init"], capture_output=True, check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.email", "t@example.com"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.name", "Tester"], check=True)
            (repo / "service.py").write_text(
                "def pay():\n    # TODO: wire gateway\n    raise NotImplementedError()\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-m", "initial"], capture_output=True, check=True)

            # 1) Default (no flags) -> full scan catches committed slop
            out_default = StringIO()
            with patch("sys.stdout", out_default):
                code_default = audit_diff.main(["--repo", tmp, "--json"])
            self.assertEqual(code_default, 1)
            payload = json.loads(out_default.getvalue())
            self.assertEqual(payload["scope"]["mode"], "all")
            self.assertEqual(payload["scope"]["files_scanned"], 1)
            self.assertGreaterEqual(payload["critical"], 2)

            # 2) --changed -> nothing to audit + helpful tip
            out_changed = StringIO()
            with patch("sys.stdout", out_changed):
                code_changed = audit_diff.main(["--repo", tmp, "--changed"])
            self.assertEqual(code_changed, 0)
            text = out_changed.getvalue()
            self.assertIn("nothing to audit", text)
            self.assertIn("--all", text)

            # 3) Stop hook still ignores already-committed legacy slop
            self.assertEqual(
                hook_stop.evaluate_stop_hook(
                    {"cwd": tmp, "terminationReason": "NO_TOOL_CALL", "continuationActive": False},
                    mode="antigravity",
                ),
                {},
            )

    def test_non_git_plain_directory_can_be_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "App.swift").write_text(
                'func load() { fatalError("Not implemented") }\n',
                encoding="utf-8",
            )
            out = StringIO()
            with patch("sys.stdout", out):
                code = audit_diff.main(["--repo", tmp, "--json"])
            self.assertEqual(code, 1)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["scope"]["mode"], "all")
            self.assertEqual(payload["findings"][0]["rule"], "placeholder-stub")

    def test_full_scan_skips_pods_and_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Pods" / "SomePod").mkdir(parents=True)
            (root / "Pods" / "SomePod" / "Pod.swift").write_text("// TODO: pod internal\n", encoding="utf-8")
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / "index.js").write_text("// TODO: vendor\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "clean.py").write_text("def ok():\n    return 1\n", encoding="utf-8")

            out = StringIO()
            with patch("sys.stdout", out):
                code = audit_diff.main(["--repo", tmp])
            self.assertEqual(code, 0)
            self.assertIn("CLEAN — scanned 1 file(s)", out.getvalue())

    def test_max_findings_caps_text_but_json_keeps_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines = "\n".join(f"# TODO: item {i}" for i in range(5))
            (root / "many.py").write_text(lines + "\n", encoding="utf-8")

            text_out = StringIO()
            with patch("sys.stdout", text_out):
                code_text = audit_diff.main(["--repo", tmp, "--max-findings", "2"])
            self.assertEqual(code_text, 1)
            rendered = text_out.getvalue()
            self.assertIn("Summary: placeholder-stub: 5", rendered)
            self.assertIn("3 more finding(s) omitted", rendered)

            json_out = StringIO()
            with patch("sys.stdout", json_out):
                audit_diff.main(["--repo", tmp, "--max-findings", "2", "--json"])
            payload = json.loads(json_out.getvalue())
            self.assertEqual(len(payload["findings"]), 5)


if __name__ == "__main__":
    unittest.main()
