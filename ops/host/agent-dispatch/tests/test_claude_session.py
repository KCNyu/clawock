import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("claude_session", Path(__file__).parents[1] / "claude-session.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SID = "aaaaaaaa-1111-2222-3333-444444444444"
LIMIT = "You've hit your session limit · resets 2:10am (Asia/Shanghai)"


class ResolveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "claude"
        self.start = self.root / "start"   # the directory the session was started in
        (self.start / "wt").mkdir(parents=True)
        self.agents = self.root / "agents.json"
        self.agents.write_text("[]")
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def transcript(self, *events, sid=SID, cwd=None):
        d = self.home / "projects" / module.project_key(str(cwd or self.start))
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))

    def job(self, short, state, sid=SID):
        d = self.home / "jobs" / short
        d.mkdir(parents=True)
        (d / "state.json").write_text(json.dumps(
            {"state": state, "detail": LIMIT if state == "blocked" else state, "sessionId": sid,
             "daemonShort": short, "cwd": str(self.start)}))

    def live(self, **entry):
        self.agents.write_text(json.dumps([{"sessionId": SID, "pid": 4242, **entry}]))

    def resolve(self, ref):
        return module.resolve(ref, self.agents)

    def test_dead_terminal_session_resumes_from_its_project_not_its_last_cd(self):
        # The SSH-drop case (765798b5, 2026-10-20): started in /root, it had cd'ed into a worktree
        # and was refused by its usage limit, the CLI's own wait died with the terminal.
        self.transcript({"type": "user", "cwd": str(self.start)},
                        {"type": "assistant", "cwd": str(self.start / "wt")},
                        {"type": "assistant", "cwd": str(self.start / "wt"), "isApiErrorMessage": True,
                         "error": "rate_limit", "timestamp": "2026-10-19T16:04:04.898Z",
                         "message": {"content": [{"type": "text", "text": LIMIT}]}},
                        {"type": "system", "cwd": str(self.start / "wt"),
                         "content": "Usage limit reached · continuing automatically at 2:10am"})
        out = self.resolve(SID[:8])
        self.assertEqual((out["SESSION"], out["CWD"], out["ACTION"]), (SID, str(self.start), "resume"))
        self.assertEqual((out["LIMIT_TEXT"], out["LIMIT_AT"]), (LIMIT, "2026-10-19T16:04:04.898Z"))
        self.assertEqual(out["BG_ID"], "")

    def test_a_limit_followed_by_work_is_history(self):
        self.transcript({"type": "assistant", "cwd": str(self.start), "isApiErrorMessage": True, "error": "rate_limit",
                         "message": {"content": [{"type": "text", "text": LIMIT}]}},
                        {"type": "assistant", "cwd": str(self.start), "message": {"content": [{"type": "text", "text": "done"}]}})
        self.assertEqual(self.resolve(SID)["LIMIT_TEXT"], "")

    def test_background_session_blocked_on_its_limit_is_stopped_first(self):
        self.transcript({"type": "user", "cwd": str(self.start)})
        self.job("aaaaaaaa", "blocked")
        self.live(kind="background", id="aaaaaaaa", state="blocked")
        out = self.resolve("aaaaaaaa")
        self.assertEqual((out["BG_ID"], out["BG_STATE"], out["ACTION"]), ("aaaaaaaa", "blocked", "stop-then-resume"))
        self.assertEqual(out["BG_DETAIL"], LIMIT)

    def test_stopped_background_session_resumes_without_a_stop(self):
        self.transcript({"type": "user", "cwd": str(self.start)})
        self.job("aaaaaaaa", "stopped")
        self.assertEqual(self.resolve(SID)["ACTION"], "resume")

    def test_refusals(self):
        self.transcript({"type": "user", "cwd": str(self.start)})
        self.job("aaaaaaaa", "working")
        self.live(kind="background", id="aaaaaaaa", state="working")
        with self.assertRaisesRegex(module.Refused, "still working"):
            self.resolve("aaaaaaaa")
        # A terminal, or the headless claude -p of a dispatched task.
        self.live(kind="interactive", status="busy")
        with self.assertRaisesRegex(module.Refused, "pid 4242, interactive"):
            self.resolve(SID)
        self.agents.write_text("")
        with self.assertRaisesRegex(module.Refused, "gave no answer"):
            self.resolve(SID)
        with self.assertRaisesRegex(module.Refused, "no claude session"):
            self.resolve("bbbbbbbb")
        with self.assertRaisesRegex(module.Refused, "is not a background session id"):
            self.resolve("../etc")

    def test_ambiguous_prefix_and_missing_directory(self):
        self.transcript({"type": "user", "cwd": str(self.start)})
        self.transcript({"type": "user", "cwd": str(self.start)}, sid=SID[:8] + "-9999-2222-3333-444444444444")
        with self.assertRaisesRegex(module.Refused, "matches 2 sessions"):
            self.resolve(SID[:8])
        gone = self.root / "gone"
        self.transcript({"type": "user", "cwd": str(gone)}, sid="cccccccc-1111-2222-3333-444444444444", cwd=gone)
        with self.assertRaisesRegex(module.Refused, "no longer exists"):
            self.resolve("cccccccc")

    def test_job_without_a_transcript_has_nothing_to_resume(self):
        self.job("aaaaaaaa", "blocked")
        with self.assertRaisesRegex(module.Refused, "no transcript"):
            self.resolve("aaaaaaaa")


if __name__ == "__main__":
    unittest.main()
