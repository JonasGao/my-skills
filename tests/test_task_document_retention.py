#!/usr/bin/env python3
"""Regression tests for system-temporary task documents."""

import contextlib
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RELAY_SCRIPT = ROOT / "zellij-relay-prompt" / "scripts" / "relay.py"
NEW_PANE_SCRIPT = ROOT / "zellij-agent-pane" / "scripts" / "new-pane.sh"


def load_relay_module():
    spec = importlib.util.spec_from_file_location("relay_under_test", RELAY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RelayTaskDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.environment = mock.patch.dict(
            os.environ,
            {
                "TMPDIR": self.temp_dir.name,
                "TEMP": self.temp_dir.name,
                "TMP": self.temp_dir.name,
            },
        )
        self.environment.start()
        self.previous_tempdir = tempfile.tempdir
        tempfile.tempdir = None
        self.relay = load_relay_module()

    def tearDown(self):
        tempfile.tempdir = self.previous_tempdir
        self.environment.stop()
        self.temp_dir.cleanup()

    def run_relay(self, pane, prompt_file=None):
        calls = []

        def sender(action, *extra):
            calls.append((action, extra))
            return SimpleNamespace(returncode=0, stderr="")

        self.assertIsNotNone(prompt_file)
        arguments = [str(RELAY_SCRIPT), pane, str(prompt_file)]

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(self.relay, "pane_exists", return_value=True),
            mock.patch.object(self.relay, "make_sender", return_value=sender),
            mock.patch.object(sys, "argv", arguments),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.relay.main()
        return calls, stdout.getvalue(), stderr.getvalue()

    def test_long_relay_retains_a_private_unique_system_temp_file(self):
        pane = "terminal_42"
        source_file = self.temp_path / f"zellij-relay-prompt-{pane}.md"
        task = "x" * 2001
        source_file.write_text(task, encoding="utf-8")

        calls, _, stderr = self.run_relay(pane, source_file)

        retained = list(self.temp_path.glob(f"zellij-relay-long-{pane}-*.md"))
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_text(encoding="utf-8"), task)
        self.assertFalse(source_file.exists())
        self.assertIn(str(retained[0]), stderr)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(retained[0].stat().st_mode) & 0o077, 0)

        sent_text = next(extra[0] for action, extra in calls if action == "write-chars")
        self.assertIn(str(retained[0]), sent_text)
        self.assertNotIn("删除", sent_text)

    def test_short_relay_uses_unique_staged_file_and_sender_cleanup(self):
        pane = "terminal_42"
        source_file = self.temp_path / f"zellij-relay-prompt-{pane}.md"
        source_file.write_text("small task", encoding="utf-8")

        calls, _, _ = self.run_relay(pane, source_file)

        self.assertFalse(source_file.exists())
        self.assertEqual(list(self.temp_path.glob("zellij-relay-long-*.md")), [])
        sent_text = next(extra[0] for action, extra in calls if action == "write-chars")
        self.assertEqual(sent_text, "small task")

    def test_long_relays_to_the_same_pane_keep_separate_task_documents(self):
        pane = "terminal_42"
        source_file = self.temp_path / f"zellij-relay-prompt-{pane}.md"
        first_task = "a" * 2001
        second_task = "b" * 2001

        source_file.write_text(first_task, encoding="utf-8")
        self.run_relay(pane, source_file)
        source_file.write_text(second_task, encoding="utf-8")
        self.run_relay(pane, source_file)

        retained = list(self.temp_path.glob(f"zellij-relay-long-{pane}-*.md"))
        self.assertEqual(len(retained), 2)
        self.assertEqual(
            {path.read_text(encoding="utf-8") for path in retained},
            {first_task, second_task},
        )


@unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "requires bash and jq")
class NewPaneTaskDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.bin_dir = self.temp_path / "bin"
        self.bin_dir.mkdir()
        self.write_chars_log = self.temp_path / "write-chars.txt"
        zellij = self.bin_dir / "zellij"
        zellij.write_text(
            """#!/usr/bin/env bash
set -eu
case "${2:-}" in
    list-panes)
        printf '[{"id": 1, "tab_id": 7, "is_focused": true}]\\n'
        ;;
    new-pane)
        printf 'terminal_42\\n'
        ;;
    dump-screen)
        path=""
        while [ "$#" -gt 0 ]; do
            if [ "$1" = "--path" ]; then
                path="$2"
                break
            fi
            shift
        done
        printf 'READY\\n' >"$path"
        ;;
    write-chars)
        printf '%s' "${!#}" >"$ZAP_TEST_WRITE_CHARS_LOG"
        ;;
esac
""",
            encoding="utf-8",
        )
        zellij.chmod(0o755)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_new_pane(self, prompt):
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}{os.pathsep}{environment['PATH']}",
                "TMPDIR": self.temp_dir.name,
                "TEMP": self.temp_dir.name,
                "TMP": self.temp_dir.name,
                "ZAP_AGENT_CMD": "test-agent",
                "ZAP_READY_MARK": "READY",
                "ZAP_TEST_WRITE_CHARS_LOG": str(self.write_chars_log),
                "ZELLIJ_PANE_ID": "",
            }
        )
        return subprocess.run(
            ["bash", str(NEW_PANE_SCRIPT), "right", str(ROOT), prompt],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def test_long_initial_prompt_is_retained_in_system_temp_directory(self):
        result = self.run_new_pane("x" * 2001)

        self.assertEqual(result.returncode, 0, result.stderr)
        match = re.search(r"Sent prompt pointer to (.+) \(prompt was 2001 bytes\)", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        retained = Path(match.group(1))
        self.assertEqual(retained.parent, self.temp_path)
        self.assertEqual(retained.read_text(encoding="utf-8"), "x" * 2001)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(retained.stat().st_mode) & 0o077, 0)
        self.assertNotIn("Delete", self.write_chars_log.read_text(encoding="utf-8"))

    def test_short_initial_prompt_remains_sender_cleaned(self):
        result = self.run_new_pane("small task")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.temp_path.glob("zellij-agent-init-*.md")), [])
        self.assertEqual(self.write_chars_log.read_text(encoding="utf-8"), "small task")


if __name__ == "__main__":
    unittest.main()
