"""Script-level tests for the tracked delegation reply protocol."""

import json
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "zellij-relay-prompt" / "scripts"
CREATE = SCRIPTS / "create-reply-route.py"
WAIT = SCRIPTS / "wait-for-reply.py"
REPLY = SCRIPTS / "reply-to-request.py"
CANCEL = SCRIPTS / "cancel-reply.py"


class ReplyProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, script, *args):
        return subprocess.run(
            ["python3", str(script), *map(str, args), "--temp-dir", str(self.root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def create(self):
        result = self.run_script(CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(uuid.UUID(payload["request_id"]))
        self.assertIn("wait_command", payload)
        self.assertIn("reply_command", payload)
        self.assertIn("cancel_command", payload)
        route = Path(payload["route_dir"])
        self.assertEqual(route.parent, self.root)
        self.assertEqual(route.stat().st_mode & 0o777, 0o700)
        self.assertTrue((route / "wake.fifo").is_fifo())
        return payload["request_id"], route

    def write_summary(self, text="finished"):
        path = self.root / f"summary-{time.time_ns()}"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reply_is_durable_before_waiter_and_copies_result(self):
        request_id, route = self.create()
        summary = self.write_summary("success")
        result_file = self.root / "full.txt"
        result_file.write_bytes(b"complete output\x00")
        submitted = self.run_script(REPLY, request_id, "succeeded", summary, result_file)
        self.assertEqual(submitted.returncode, 0, submitted.stderr)
        waited = self.run_script(WAIT, request_id)
        self.assertEqual(waited.returncode, 0, waited.stderr)
        record = json.loads(waited.stdout)
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(Path(record["result_file"]).read_bytes(), b"complete output\x00")
        self.assertEqual(json.loads((route / "reply.json").read_text())["summary"], "success")

    def test_background_waiter_wakes_on_reply(self):
        request_id, _ = self.create()
        waiter = subprocess.Popen(
            ["python3", str(WAIT), request_id, "--temp-dir", str(self.root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(0.08)
            summary = self.write_summary("worker returned")
            submitted = self.run_script(REPLY, request_id, "failed", summary)
            self.assertEqual(submitted.returncode, 0, submitted.stderr)
            stdout, stderr = waiter.communicate(timeout=2)
            self.assertEqual(waiter.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["status"], "failed")
        finally:
            if waiter.poll() is None:
                waiter.kill()
                waiter.wait()

    def test_timeout_writes_tombstone_and_late_reply_is_rejected(self):
        request_id, route = self.create()
        waited = self.run_script(WAIT, request_id, "--timeout", "0.05")
        self.assertEqual(waited.returncode, 0, waited.stderr)
        self.assertEqual(json.loads(waited.stdout)["status"], "timed_out")
        summary = self.write_summary("too late")
        late = self.run_script(REPLY, request_id, "succeeded", summary)
        self.assertNotEqual(late.returncode, 0)
        self.assertIn("different terminal reply", late.stderr)
        self.assertEqual(json.loads((route / "reply.json").read_text())["status"], "timed_out")

    def test_reply_and_cancel_race_has_one_authoritative_record(self):
        request_id, route = self.create()
        summary = self.write_summary("race")
        reply = subprocess.Popen(
            ["python3", str(REPLY), request_id, "succeeded", str(summary), "--temp-dir", str(self.root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        cancel = subprocess.Popen(
            ["python3", str(CANCEL), request_id, "--temp-dir", str(self.root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        reply.communicate(timeout=2)
        cancel.communicate(timeout=2)
        self.assertIn(reply.returncode, (0, 1))
        self.assertIn(cancel.returncode, (0, 1))
        record = json.loads((route / "reply.json").read_text(encoding="utf-8"))
        self.assertIn(record["status"], ("succeeded", "cancelled"))
        self.assertEqual(sum(code == 0 for code in (reply.returncode, cancel.returncode)), 1)

    def test_waiter_can_restart_after_crash_and_read_later_reply(self):
        request_id, _ = self.create()
        waiter = subprocess.Popen(
            ["python3", str(WAIT), request_id, "--temp-dir", str(self.root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.08)
        waiter.kill()
        waiter.communicate(timeout=2)
        summary = self.write_summary("after restart")
        submitted = self.run_script(REPLY, request_id, "succeeded", summary)
        self.assertEqual(submitted.returncode, 0, submitted.stderr)
        restarted = self.run_script(WAIT, request_id)
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertEqual(json.loads(restarted.stdout)["summary"], "after restart")

    def test_tampered_result_path_is_rejected_by_waiter(self):
        request_id, route = self.create()
        summary = self.write_summary("bad path")
        result = self.root / "full"
        result.write_text("result", encoding="utf-8")
        submitted = self.run_script(REPLY, request_id, "succeeded", summary, result)
        self.assertEqual(submitted.returncode, 0, submitted.stderr)
        record_path = route / "reply.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["result_file"] = str(self.root / ".." / "outside")
        record_path.write_text(json.dumps(record), encoding="utf-8")
        waited = self.run_script(WAIT, request_id)
        self.assertNotEqual(waited.returncode, 0)
        self.assertIn("result_file", waited.stderr)

    def test_cancel_wakes_waiter_and_rejects_late_reply(self):
        request_id, _ = self.create()
        waiter = subprocess.Popen(
            ["python3", str(WAIT), request_id, "--temp-dir", str(self.root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(0.08)
            cancelled = self.run_script(CANCEL, request_id)
            self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
            stdout, stderr = waiter.communicate(timeout=2)
            self.assertEqual(waiter.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["status"], "cancelled")
            summary = self.write_summary("late")
            late = self.run_script(REPLY, request_id, "failed", summary)
            self.assertNotEqual(late.returncode, 0)
        finally:
            if waiter.poll() is None:
                waiter.kill()
                waiter.wait()

    def test_identical_duplicate_is_idempotent_but_different_reply_conflicts(self):
        request_id, _ = self.create()
        summary = self.write_summary("same")
        first = self.run_script(REPLY, request_id, "succeeded", summary)
        duplicate = self.run_script(REPLY, request_id, "succeeded", summary)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
        different = self.write_summary("different")
        conflict = self.run_script(REPLY, request_id, "succeeded", different)
        self.assertNotEqual(conflict.returncode, 0)

    def test_only_one_waiter_can_run(self):
        request_id, _ = self.create()
        first = subprocess.Popen(
            ["python3", str(WAIT), request_id, "--temp-dir", str(self.root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(0.08)
            second = self.run_script(WAIT, request_id, "--timeout", "0.01")
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("already running", second.stderr)
            cancelled = self.run_script(CANCEL, request_id)
            self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
            first.communicate(timeout=2)
        finally:
            if first.poll() is None:
                first.kill()
                first.wait()

    def test_summary_limit_and_route_path_validation(self):
        request_id, _ = self.create()
        oversized = self.write_summary("x" * 4097)
        rejected = self.run_script(REPLY, request_id, "succeeded", oversized)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("4 KiB", rejected.stderr)
        invalid = self.run_script(WAIT, "../" + request_id)
        self.assertNotEqual(invalid.returncode, 0)


if __name__ == "__main__":
    unittest.main()
