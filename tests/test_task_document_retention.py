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
import time
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
        self.new_pane_args_log = self.temp_path / "new-pane-args.txt"
        self.agent_output = self.temp_path / "agent-output.txt"
        self.agent_pid_file = self.temp_path / "agent-pid.txt"
        zellij = self.bin_dir / "zellij"
        zellij.write_text(
            """#!/usr/bin/env bash
set -eu
case "${2:-}" in
    list-panes)
        printf '[{"id": 1, "tab_id": 7, "is_focused": true}]\\n'
        ;;
    new-pane)
        printf '%s\\n' "$@" >"$ZAP_TEST_NEW_PANE_ARGS_LOG"
        while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
            shift
        done
        shift
        "$@" >"$ZAP_TEST_AGENT_STDOUT" 2>"$ZAP_TEST_AGENT_STDERR" &
        printf '%s\\n' "$!" >"$ZAP_TEST_AGENT_PID_FILE"
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
        self.write_agent_script()

    def tearDown(self):
        if self.agent_pid_file.exists():
            try:
                pid = int(self.agent_pid_file.read_text(encoding="utf-8").strip())
                os.kill(pid, 15)
            except (ValueError, ProcessLookupError):
                pass
        self.temp_dir.cleanup()

    def run_new_pane(self, prompt="", cwd=ROOT, **overrides):
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
                "ZAP_TEST_NEW_PANE_ARGS_LOG": str(self.new_pane_args_log),
                "ZAP_TEST_AGENT_OUTPUT": str(self.agent_output),
                "ZAP_TEST_AGENT_PID_FILE": str(self.agent_pid_file),
                "ZAP_TEST_AGENT_STDOUT": str(self.temp_path / "agent-stdout.txt"),
                "ZAP_TEST_AGENT_STDERR": str(self.temp_path / "agent-stderr.txt"),
                "ZELLIJ_PANE_ID": "",
            }
        )
        environment.pop("ZAP_AGENT_INIT", None)
        environment.update(overrides)
        return subprocess.run(
            ["bash", str(NEW_PANE_SCRIPT), str(cwd), prompt],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def new_pane_arguments(self):
        return self.new_pane_args_log.read_text(encoding="utf-8").splitlines()

    def wait_for_agent_output(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.agent_output.exists():
                return self.agent_output.read_text(encoding="utf-8")
            time.sleep(0.02)
        self.fail("agent did not write its output")

    def write_agent_script(self):
        agent = self.bin_dir / "test-agent"
        agent.write_text(
            """#!/usr/bin/env bash
printf 'value=%s\\n' "${INIT_VALUE-unset}" >"$ZAP_TEST_AGENT_OUTPUT"
while :; do sleep 1; done
""",
            encoding="utf-8",
        )
        agent.chmod(0o755)
        return agent

    def test_tiled_pane_uses_automatic_placement(self):
        result = self.run_new_pane(ZAP_DEBUG="1")

        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = self.new_pane_arguments()
        self.assertNotIn("--direction", arguments)
        self.assertNotIn("--floating", arguments)
        self.assertIn("placement=automatic-tiled", result.stderr)
        self.assertNotIn("direction=", result.stderr)

    def test_floating_pane_remains_explicit(self):
        result = self.run_new_pane(ZAP_FLOATING="1", ZAP_DEBUG="1")

        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = self.new_pane_arguments()
        self.assertIn("--floating", arguments)
        self.assertNotIn("--direction", arguments)
        self.assertIn("placement=floating", result.stderr)

    def test_removed_direction_argument_fails_before_configuration_check(self):
        environment = os.environ.copy()
        environment["PATH"] = f"{self.bin_dir}{os.pathsep}{environment['PATH']}"
        environment.pop("ZAP_AGENT_CMD", None)
        environment.pop("ZAP_INITIAL_PROMPT", None)

        for direction in ("right", "down", "left", "up"):
            with self.subTest(direction=direction):
                result = subprocess.run(
                    ["bash", str(NEW_PANE_SCRIPT), direction, str(ROOT)],
                    text=True,
                    capture_output=True,
                    env=environment,
                    check=False,
                )

                self.assertEqual(result.returncode, 1)
                self.assertIn(
                    f"START_FAILED: direction argument '{direction}' was removed; "
                    "use new-pane.sh [cwd] [initial-prompt]; tiled panes use "
                    "automatic placement",
                    result.stderr,
                )
                self.assertNotIn("ACTION_REQUIRED", result.stderr)

    def test_empty_cwd_uses_current_directory(self):
        result = self.run_new_pane(cwd="")

        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_agent_init_file_is_sourced_relative_to_target_cwd(self):
        init_file = self.temp_path / "agent-init.sh"
        init_file.write_text("export INIT_VALUE=from-init\n", encoding="utf-8")

        result = self.run_new_pane(
            cwd=self.temp_path,
            ZAP_AGENT_INIT="agent-init.sh",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.wait_for_agent_output(), "value=from-init\n")

    def test_agent_env_overrides_init_file_for_agent_command(self):
        init_file = self.temp_path / "agent-init.sh"
        init_file.write_text("export INIT_VALUE=from-init\n", encoding="utf-8")

        result = self.run_new_pane(
            ZAP_AGENT_INIT=str(init_file),
            ZAP_AGENT_ENV="INIT_VALUE=from-override",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.wait_for_agent_output(), "value=from-override\n")

    def test_agent_command_can_call_function_from_init_file(self):
        init_file = self.temp_path / "agent-init.sh"
        init_file.write_text(
            """start-test-agent() {
    printf 'value=%s\\n' "${INIT_VALUE-unset}" >"$ZAP_TEST_AGENT_OUTPUT"
    while :; do sleep 1; done
}
export INIT_VALUE=from-function-init
""",
            encoding="utf-8",
        )

        result = self.run_new_pane(
            ZAP_AGENT_INIT=str(init_file),
            ZAP_AGENT_CMD="start-test-agent",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.wait_for_agent_output(), "value=from-function-init\n")

    def test_missing_agent_init_file_fails_before_creating_pane(self):
        result = self.run_new_pane(
            cwd=self.temp_path,
            ZAP_AGENT_INIT="missing-init.sh",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("agent init file", result.stderr)
        self.assertIn(str(self.temp_path / "missing-init.sh"), result.stderr)

    def test_agent_init_failure_reports_init_status(self):
        init_file = self.temp_path / "agent-init.sh"
        init_file.write_text("return 7\n", encoding="utf-8")

        result = self.run_new_pane(ZAP_AGENT_INIT=str(init_file))

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"agent init file '{init_file}' failed with status 7",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
