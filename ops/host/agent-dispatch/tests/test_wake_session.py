"""Wake acknowledgment, replay and guards without systemd or real conversations."""
import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("wake_session", Path(__file__).parents[1] / "wake-session.py")
wake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wake)
KEY = "agent:main:test:direct:disposable"


class WakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.box = self.root / ".wake" / wake.session_hash(KEY)
        self.task = self.make_task("task-a")
        self.text = self.root / "notice.txt"
        self.text.write_text("task done\nfull report must not enter the turn")
        self.addCleanup(patch.stopall)
        patch.object(wake, "STATE", self.root / ".wake").start()
        patch.object(wake, "OFF", self.root / "wake.off").start()
        patch.object(wake, "limit", side_effect=lambda name, default: default).start()
        patch.dict(os.environ, {"AGENT_DISPATCH_WAKE_SPAWN": "inline"}).start()

    def make_task(self, name, depth=0):
        task = self.root / name
        task.mkdir()
        (task / "meta.env").write_text(
            f"ID={name}\nORIGIN_SESSION={KEY}\nWAKE_DEPTH={depth}\nNOTIFY=weixin,telegram\n")
        return task

    def enqueue(self, task=None, event="end"):
        return wake.cmd_enqueue(task or self.task, event, self.text)

    def drain(self):
        return wake.cmd_drain(self.box.name)

    def pending(self):
        return sorted((self.box / "spool").glob("*.json"))

    def fake_run(self, rc=0, status="ok", stdout=None):
        real_run = subprocess.run

        def run(cmd, **kwargs):
            if cmd[0] == "bash":  # read_env uses a real, short shell
                return real_run(cmd, **kwargs)
            self.turns.append(cmd)
            self.assertEqual(len(self.pending()), 1)
            self.assertFalse((self.box / "seen" / "task-a.end").exists())
            self.assertNotIn("--deliver", cmd)
            self.assertEqual(cmd[cmd.index("--timeout") + 1], "600")
            message = (self.box / "message.md").read_text()
            self.assertIn("本轮执行上限 600 秒", message)
            self.assertIn("不要 sleep 或循环 poll", message)
            return subprocess.CompletedProcess(cmd, rc, stdout if stdout is not None else
                                               json.dumps({"status": status, "runId": "test-run"}), "")
        self.turns = []
        return patch.object(wake.subprocess, "run", side_effect=run)

    def test_notice_snapshot_and_independent_wake_status(self):
        (self.task / "result.env").write_text("NOTIFIED=telegram\nNOTIFY_FAILED=weixin\nNOTIFY_AT=test\n")
        with self.fake_run(status="timeout"):
            self.enqueue()
        status = json.loads((self.task / "wake-end.json").read_text())
        self.assertEqual((status["state"], status["attempts"]), ("failed", 1))
        self.assertEqual(status["last_error"], "rc=0 status=timeout")
        self.assertIsNone(status["acknowledged_at"])
        (self.task / "result.env").write_text("NOTIFIED=weixin,telegram\nNOTIFY_FAILED=\n")
        with self.fake_run():
            self.drain()
        message = (self.box / "message.md").read_text()
        self.assertIn('"NOTIFY_FAILED": "weixin"', message)  # original event, not a later notice
        self.assertNotIn("已经在手机上收到", message)
        status = json.loads((self.task / "wake-end.json").read_text())
        self.assertEqual((status["state"], status["attempts"]), ("acknowledged", 2))
        self.assertTrue(status["acknowledged_at"])

    def test_failures_retain_original_event_and_reenqueue_succeeds(self):
        for rc, status, stdout in ((0, "timeout", None), (1, "error", None),
                                   (1, "ok", None), (124, "?", ""), (0, "?", "bad JSON")):
            with self.subTest(rc=rc, status=status):
                with self.fake_run(rc, status, stdout):
                    self.assertEqual(self.enqueue(), 0)
                    self.assertEqual(len(self.turns), 1)  # no automatic retry
                original = self.pending()[0].read_bytes()
                self.assertFalse((self.box / "inflight").exists())
                self.text.write_text("replacement notice")
                with self.fake_run():
                    self.enqueue()
                self.assertFalse(self.pending())
                self.assertEqual((self.box / "seen" / "task-a.end").read_text(), "ok\n")
                self.assertIn(json.loads(original)["text"], (self.box / "message.md").read_text())
                with self.fake_run():
                    self.enqueue()
                    self.assertFalse(self.turns)
                (self.box / "seen" / "task-a.end").unlink()
                (self.box / "history").unlink()  # independent scenario, no cap carryover

    def test_launch_error_retains_event_for_direct_drain(self):
        real_run = subprocess.run

        def broken(cmd, **kwargs):
            if cmd[0] == "bash":
                return real_run(cmd, **kwargs)
            raise OSError("cannot launch")
        with patch.object(wake.subprocess, "run", side_effect=broken):
            self.enqueue()
        self.assertEqual(len(self.pending()), 1)
        self.assertIn("rc=127", (self.task / "run.log").read_text())
        with self.fake_run():
            self.drain()
        self.assertFalse(self.pending())

    def test_pending_duplicate_coalesces_even_if_unit_launch_fails(self):
        real_run = subprocess.run

        def unit(cmd, **kwargs):
            if cmd[0] == "bash":
                return real_run(cmd, **kwargs)
            self.assertEqual(cmd[0], "systemd-run")
            return subprocess.CompletedProcess(cmd, 1, "", "unit failed")
        with patch.dict(os.environ, {"AGENT_DISPATCH_WAKE_SPAWN": "unit"}), \
                patch.object(wake.subprocess, "run", side_effect=unit):
            self.enqueue()
            original = self.pending()[0].read_bytes()
            self.text.write_text("changed")
            self.enqueue()
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual(self.pending()[0].read_bytes(), original)
        with self.fake_run():
            self.drain()

    def test_off_depth_success_and_hourly_cap_remain_silent(self):
        with self.fake_run():
            wake.OFF.touch()
            self.enqueue()
            wake.OFF.unlink()
            self.enqueue(self.make_task("too-deep", depth=2))
            self.assertFalse(self.turns)
            self.enqueue()
            self.enqueue()  # acknowledged event stays silent
            self.assertEqual(len(self.turns), 1)
        # A failed event stays recoverable even when the switch/cap blocks the next drain.
        (self.box / "seen" / "task-a.end").unlink()
        with self.fake_run(status="timeout"):
            self.enqueue()
        with self.fake_run():
            wake.OFF.touch()
            self.drain()
            wake.OFF.unlink()
            (self.box / "history").write_text("\n".join([str(time.time())] * 6))
            self.enqueue()
            self.drain()
            self.assertFalse(self.turns)
            self.assertEqual(len(self.pending()), 1)
            (self.box / "history").write_text(str(time.time() - 3601))
            self.drain()
            self.assertEqual(len(self.turns), 1)

    def test_batch_failure_and_arrival_during_turn_only_acknowledge_snapshot(self):
        real_run = subprocess.run
        task_b, task_c = self.make_task("task-b"), self.make_task("task-c")
        turns = []

        def run(cmd, **kwargs):
            if cmd[0] == "bash":
                return real_run(cmd, **kwargs)
            if cmd[0] == "systemd-run":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            turns.append(cmd)
            if len(turns) == 1:
                self.assertEqual(len(self.pending()), 2)
                return subprocess.CompletedProcess(cmd, 0, '{"status":"timeout"}', "")
            if len(turns) == 2:
                # Enqueue can run while the turn holds its long lock; it must not block,
                # overwrite the batch, or have its new event acknowledged by this turn.
                self.enqueue(task_c)
            return subprocess.CompletedProcess(cmd, 0, '{"status":"ok"}', "")
        with patch.dict(os.environ, {"AGENT_DISPATCH_WAKE_SPAWN": "unit"}), \
                patch.object(wake.subprocess, "run", side_effect=run):
            self.enqueue()
            self.enqueue(task_b, "quota")
            self.drain()
            self.assertEqual(len(self.pending()), 2)
            self.assertFalse(list((self.box / "seen").glob("*")))
            self.drain()
            self.assertEqual([p.name for p in self.pending()], ["task-c.end.json"])
            self.drain()
        self.assertFalse(self.pending())
        self.assertEqual(len(turns), 3)

    def test_acknowledged_spool_after_crash_is_not_replayed(self):
        with self.fake_run(status="timeout"):
            self.enqueue()
        (self.box / "seen" / "task-a.end").write_text("ok\n")
        with self.fake_run():
            self.drain()
            self.assertFalse(self.turns)
        self.assertFalse(self.pending())

    def test_legacy_queued_marker_does_not_discard_spool_on_upgrade(self):
        with self.fake_run(status="timeout"):
            self.enqueue()
        (self.box / "seen" / "task-a.end").touch()  # old enqueue-time marker
        with patch.object(wake.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, '{"status":"ok"}', "")) as run:
            self.drain()
            self.assertEqual(run.call_count, 1)
        self.assertFalse(self.pending())


if __name__ == "__main__":
    unittest.main()
