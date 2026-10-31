"""The dispatch mandate: immutable record, action decision, violation log (runner api 5)."""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "mandate.py"
SPEC = importlib.util.spec_from_file_location("dispatch_mandate", SRC)
MANDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANDATE)
REPO = Path(os.environ.get("CLAWOCK_REPO", Path.cwd()))
RESTART = REPO / "ops/host/restart_gateway.sh"
REFRESH = REPO / "ops/host/refresh_live.sh"


def create(directory: Path, *extra: str) -> int:
    return MANDATE.main([
        "create", "--dir", str(directory), "--task-id", "task-1", "--name", "task-1",
        "--agent", "dsh", "--cwd", "/root", "--policy-version", "dispatch-test",
        "--source-kind", "chat", "--source-id", "session-1", "--notify", "weixin,telegram",
        *extra,
    ])


class MandateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.file = self.dir / "mandate.json"

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, action: str) -> int:
        return MANDATE.main(["check", "--file", str(self.file), "--action", action,
                             "--task-dir", str(self.dir), "--source", "test"])

    def test_create_is_immutable_and_records_the_basis(self):
        self.assertEqual(create(self.dir), 0)
        data = json.loads(self.file.read_text())
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["task_id"], "task-1")
        self.assertEqual(data["policy_version"], "dispatch-test")
        self.assertEqual(data["source"], {"kind": "chat", "id": "session-1"})
        self.assertEqual(data["actions"], {"gateway.restart": "allow", "live.refresh": "allow"})
        self.assertEqual(data["notify"], {"on": "human-action", "channels": ["weixin", "telegram"]})
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o444)
        with self.assertRaises(SystemExit) as caught:
            create(self.dir)
        self.assertEqual(caught.exception.code, 2)

    def test_deny_restart_keeps_live_refresh_and_records_the_denial(self):
        self.assertEqual(create(self.dir, "--deny-restart"), 0)
        data = json.loads(self.file.read_text())
        self.assertEqual(data["actions"]["gateway.restart"], "deny")
        self.assertEqual(data["actions"]["live.refresh"], "allow")
        self.assertEqual(self.check("live.refresh"), 0)
        self.assertEqual(self.check("gateway.restart"), 3)
        rows = [json.loads(line) for line in (self.dir / "mandate-violations.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "gateway.restart")
        self.assertEqual(rows[0]["decision"], "deny")
        self.assertEqual(rows[0]["task_id"], "task-1")
        self.assertEqual(rows[0]["source"], "test")

    def test_an_action_not_granted_is_denied_not_ignored(self):
        self.assertEqual(create(self.dir), 0)
        self.assertEqual(self.check("git.force-push"), 3)

    def test_a_broken_mandate_is_refused_and_never_read_as_allow(self):
        self.file.write_text("{}")
        with self.assertRaises(SystemExit) as caught:
            self.check("gateway.restart")
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse((self.dir / "mandate-violations.jsonl").exists())

    @unittest.skipUnless(RESTART.exists(), "repo checkout with ops/host/restart_gateway.sh")
    def test_the_real_restart_wrapper_refuses_and_records_a_denied_restart(self):
        self.assertEqual(create(self.dir, "--deny-restart"), 0)
        env = {**os.environ, "AGENT_DISPATCH_TASK_ID": "task-1", "AGENT_DISPATCH_MANDATE": str(self.file)}
        refused = subprocess.run(["bash", str(RESTART), "--check"], env=env, capture_output=True, text=True)
        self.assertEqual(refused.returncode, 3)
        self.assertIn("refused", refused.stderr)
        self.assertNotIn("allows", refused.stdout)
        self.assertTrue((self.dir / "mandate-violations.jsonl").exists())

        allowed = self.dir / "allowed"
        allowed.mkdir()
        self.assertEqual(create(allowed), 0)
        env["AGENT_DISPATCH_MANDATE"] = str(allowed / "mandate.json")
        ok = subprocess.run(["bash", str(RESTART), "--check"], env=env, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("allows gateway.restart", ok.stdout)


    @unittest.skipUnless(RESTART.exists() and REFRESH.exists() and shutil.which("git"),
                         "repo checkout with the live-refresh guard and git")
    def test_refresh_live_refuses_a_denied_task_before_writing_anything(self):
        origin, live = self.dir / "origin.git", self.dir / "live"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(live)], check=True)
        (live / "README").write_text("x")
        git = ["git", "-C", str(live), "-c", "user.name=test", "-c", "user.email=test@example.com"]
        subprocess.run([*git, "add", "README"], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        subprocess.run(["git", "-C", str(live), "push", "-q", "origin", "HEAD:master"], check=True)
        task = self.dir / "task"
        task.mkdir()
        self.assertEqual(create(task, "--deny-restart"), 0)
        env = {**os.environ, "LIVE_CHECKOUT": str(live), "LIVE_REMOTE": "origin", "LIVE_BRANCH": "master",
               "AGENT_DISPATCH_TASK_ID": "task-1", "AGENT_DISPATCH_MANDATE": str(task / "mandate.json"),
               "AGENT_DISPATCH_DIR": str(REPO / "ops/host/agent-dispatch")}
        refused = subprocess.run(["bash", str(REFRESH)], env=env, capture_output=True, text=True)
        self.assertEqual(refused.returncode, 3, refused.stderr)
        self.assertIn("refused", refused.stderr)
        self.assertIn("mandate-violations.jsonl", refused.stderr)
        self.assertTrue((task / "mandate-violations.jsonl").exists())

        allowed = self.dir / "allowed"
        allowed.mkdir()
        self.assertEqual(create(allowed), 0)
        env["AGENT_DISPATCH_MANDATE"] = str(allowed / "mandate.json")
        ok = subprocess.run(["bash", str(REFRESH)], env=env, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("live checkout is at origin/master", ok.stdout)


if __name__ == "__main__":
    unittest.main()
