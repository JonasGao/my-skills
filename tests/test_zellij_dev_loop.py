#!/usr/bin/env python3
"""Lifecycle contract tests for the developer-reviewer loop."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLOSE_PANE = ROOT / "zellij-dev-loop" / "scripts" / "close-pane.sh"
SKILL = ROOT / "zellij-dev-loop" / "SKILL.md"


class ClosePaneTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.bin_dir = self.temp_path / "bin"
        self.bin_dir.mkdir()
        self.log = self.temp_path / "zellij.log"
        zellij = self.bin_dir / "zellij"
        zellij.write_text(
            """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$ZDL_TEST_ZELLIJ_LOG"
exit "${ZDL_TEST_ZELLIJ_STATUS:-0}"
""",
            encoding="utf-8",
        )
        zellij.chmod(0o755)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_close(self, *args, self_pane="1", zellij_status="0"):
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}{os.pathsep}{environment['PATH']}",
                "ZDL_TEST_ZELLIJ_LOG": str(self.log),
                "ZDL_TEST_ZELLIJ_STATUS": zellij_status,
                "ZELLIJ_PANE_ID": self_pane,
            }
        )
        return subprocess.run(
            ["bash", str(CLOSE_PANE), *args],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def calls(self):
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_closes_the_exact_saved_pane(self):
        result = self.run_close("terminal_42")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "CLOSED: pane=terminal_42\n")
        self.assertEqual(self.calls(), ["action close-pane --pane-id terminal_42"])

    def test_repeated_close_remains_successful(self):
        first = self.run_close("42")
        second = self.run_close("42")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(
            self.calls(),
            [
                "action close-pane --pane-id 42",
                "action close-pane --pane-id 42",
            ],
        )

    def test_propagates_a_zellij_close_failure(self):
        result = self.run_close("terminal_42", zellij_status="7")

        self.assertEqual(result.returncode, 7)
        self.assertIn("CLOSE_FAILED: pane=terminal_42 zellij_status=7", result.stderr)

    def test_rejects_an_invalid_or_missing_pane_id(self):
        for arguments in ((), ("plugin_42",), ("terminal_x",), ("42", "43")):
            with self.subTest(arguments=arguments):
                result = self.run_close(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("CLOSE_FAILED", result.stderr)

        self.assertEqual(self.calls(), [])

    def test_refuses_to_close_the_current_reviewer_pane(self):
        result = self.run_close("terminal_0042", self_pane="42")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to close the current pane", result.stderr)
        self.assertEqual(self.calls(), [])


class SkillLifecycleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.teardown = cls.skill.split("### 7. Teardown the loop", 1)[1].split(
            "## Best Practices", 1
        )[0]
        cls.normalized_teardown = " ".join(cls.teardown.split())

    def test_delivery_closes_before_the_final_user_response(self):
        close = self.teardown.index("bash scripts/close-pane.sh <developer-pane-id>")
        final_response = self.teardown.index("final user response")
        self.assertLess(close, final_response)

    def test_active_reply_is_cancelled_after_the_close_attempt(self):
        close = self.teardown.index("bash scripts/close-pane.sh <developer-pane-id>")
        cancel = self.teardown.index("cancel-reply.py")
        self.assertLess(close, cancel)

    def test_a_later_loop_must_create_a_fresh_pane_agent(self):
        self.assertIn(
            "A later development or fix request starts a new loop",
            self.normalized_teardown,
        )
        self.assertIn("Never rediscover or reuse", self.normalized_teardown)

    def test_close_is_mandatory_not_optional(self):
        self.assertNotIn("Optional", self.teardown)
        self.assertIn("Always teardown", self.teardown)


if __name__ == "__main__":
    unittest.main()
