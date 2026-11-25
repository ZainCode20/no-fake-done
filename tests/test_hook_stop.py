"""Unit tests for no-fake-done's Stop hook and plugin JSON manifests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import hook_stop  # noqa: E402


class TestHookStopAndManifests(unittest.TestCase):
    """Verify Stop hook decisions, loop prevention, and valid plugin JSON files."""

    def test_all_plugin_json_files_are_valid(self) -> None:
        json_paths = [
            ROOT_DIR / "plugin.json",
            ROOT_DIR / "hooks.json",
            ROOT_DIR / ".claude-plugin" / "plugin.json",
            ROOT_DIR / ".claude-plugin" / "marketplace.json",
            ROOT_DIR / "hooks" / "hooks.json",
        ]
        for path in json_paths:
            self.assertTrue(path.is_file(), f"Missing manifest: {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)

    def test_blocks_on_critical_slop_in_both_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "-C", str(repo), "init"], capture_output=True, check=True)
            (repo / "app.py").write_text("def f():\n    raise NotImplementedError()\n", encoding="utf-8")

            agy = hook_stop.evaluate_stop_hook(
                {"cwd": str(repo), "terminationReason": "NO_TOOL_CALL", "continuationActive": False},
                mode="antigravity",
            )
            self.assertEqual(agy["decision"], "continue")
            self.assertIn("placeholder-stub", agy["reason"])

            claude = hook_stop.evaluate_stop_hook(
                {"cwd": str(repo), "stop_hook_active": False},
                mode="claude",
            )
            self.assertEqual(claude["decision"], "block")
            self.assertIn("placeholder-stub", claude["reason"])

    def test_prevents_infinite_loop_when_already_continued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "-C", str(repo), "init"], capture_output=True, check=True)
            (repo / "app.py").write_text("# TODO: broken\n", encoding="utf-8")

            self.assertEqual(
                hook_stop.evaluate_stop_hook(
                    {"cwd": str(repo), "terminationReason": "NO_TOOL_CALL", "continuationActive": True},
                    mode="antigravity",
                ),
                {},
            )
            self.assertEqual(
                hook_stop.evaluate_stop_hook(
                    {"cwd": str(repo), "stop_hook_active": True},
                    mode="claude",
                ),
                {},
            )

    def test_allows_non_git_workspace_silently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(hook_stop.evaluate_stop_hook({"cwd": tmp}, mode="antigravity"), {})
            self.assertEqual(hook_stop.evaluate_stop_hook({"cwd": tmp}, mode="claude"), {})


if __name__ == "__main__":
    unittest.main()
