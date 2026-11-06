"""The optional receipt block: ask validation, the one answer, the answer chain, and later waits."""
import contextlib
import importlib.util
import io
import json
import os
import stat
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "receipt.py"
SPEC = importlib.util.spec_from_file_location("dispatch_receipt", SRC)
RECEIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECEIPT)

ORIGIN = "agent:main:test:direct:u1"
ASK = {"title": "选一个方案", "text": "两处都需要改，先做哪个？",
       "options": ["方案甲", "方案乙"], "recommend": 1, "about": "甲快，乙稳", "key": "pick-plan"}


def report(payload) -> str:
    body = json.dumps({"ask": payload}, ensure_ascii=False)
    return f"结论\nNEEDS: none\nSTATUS: DONE\n\n```agent-dispatch\n{body}\n```\n"


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "ask-task-20260101-000000"
        self.dir.mkdir()
        (self.dir / "meta.env").write_text(
            "ID=ask-task-20260101-000000\nAGENT=dsh\nNAME=ask-task\nCWD=/root\nNOTIFY=none\n"
            f"ORIGIN_SESSION={ORIGIN}\nANSWER_DEPTH=0\n")
        (self.dir / "result.env").write_text("STATE=ok\nOUTCOME=DONE\nSESSION=ses-1\n")
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        (self.bin / "systemctl").write_text("#!/bin/sh\necho inactive\n")
        (self.bin / "systemctl").chmod(0o755)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}:{self.old_path}"
        os.environ["AGENT_DISPATCH_TASKS_DIR"] = str(self.dir.parent)

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        self.tmp.cleanup()

    def parse(self, text: str) -> str:
        (self.dir / "runner-summary.txt").write_text(text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(RECEIPT.main(["parse", "--dir", str(self.dir), "--run", "1"]), 0)
        return out.getvalue()

    def answer(self, *args: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = RECEIPT.main(["answer", "--dir", str(self.dir), *args])
        return code, out.getvalue()

    def test_parse_writes_the_question_and_a_bounded_notice(self):
        self.assertIn("RECEIPT=valid", self.parse(report(ASK)))
        question = json.loads((self.dir / "question.json").read_text())
        self.assertEqual(question["state"], "open")
        self.assertEqual(question["task_id"], "ask-task-20260101-000000")
        self.assertEqual(question["asked_by_run"], 1)
        self.assertEqual(question["origin_session"], ORIGIN)
        self.assertEqual(question["options"], ["方案甲", "方案乙"])
        notice = (self.dir / "question-notice.txt").read_text()
        self.assertIn("【等你决定】", notice)
        self.assertIn("2. 方案乙（推荐）", notice)
        self.assertIn("dispatch.sh answer ask-task-20260101-000000", notice)

    def test_a_bad_block_is_invalid_and_never_writes_a_question(self):
        for payload in ({"title": "no key", "options": ["a", "b"], "recommend": 0},
                        {"title": "one option", "options": ["a"], "key": "k"},
                        {"title": "range", "options": ["a", "b"], "recommend": 9, "key": "k"}):
            self.assertIn("RECEIPT=invalid", self.parse(report(payload)))
            self.assertFalse((self.dir / "question.json").exists())
        self.assertIn("RECEIPT=invalid", self.parse("```agent-dispatch\nnot json\n```"))
        self.assertIn("RECEIPT=invalid", self.parse(
            "```agent-dispatch\n" + json.dumps({"ask": ASK}) + "\n```\n"
            "```agent-dispatch\n" + json.dumps({"ask": ASK}) + "\n```"))
        self.assertIn("RECEIPT=none", self.parse("no block here\nSTATUS: DONE"))

    def later(self, payload, deadline=None, used=0, maximum=3, status="DONE"):
        text = (f"done\nSTATUS: {status}\n\n```agent-dispatch\n"
                + json.dumps({"later": payload}, ensure_ascii=False) + "\n```")
        receipt = self.dir / "later-receipt.txt"
        receipt.write_text(text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = RECEIPT.main(["later", "--dir", str(self.dir), "--run", "1",
                                 "--deadline", str(deadline or int(time.time()) + 3600),
                                 "--min-run", "60", "--used", str(used), "--maximum", str(maximum),
                                 "--text-file", str(receipt)])
        return code, out.getvalue()

    def test_a_done_report_can_schedule_one_later_wait(self):
        at = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
        code, out = self.later({"at": at, "about": "查 CI 是否绿", "key": "ci-check"})
        self.assertEqual(code, 0)
        self.assertIn("LATER_STATE=wait", out)
        later = json.loads((self.dir / "later.json").read_text())
        self.assertEqual(later["state"], "waiting")
        self.assertEqual(later["key"], "ci-check")
        self.assertEqual(later["about"], "查 CI 是否绿")
        self.assertEqual(later["attempt"], 1)
        self.assertIn("查 CI 是否绿", (self.dir / "later-prompt.txt").read_text())

    def test_later_requires_a_future_zoned_time_and_a_done_report(self):
        now = datetime.now(timezone.utc)
        cases = [
            ({"at": (now - timedelta(seconds=5)).isoformat(), "about": "x", "key": "k"}, {}),
            ({"at": (now + timedelta(seconds=120)).replace(tzinfo=None).isoformat(), "about": "x", "key": "k"}, {}),
            ({"at": (now + timedelta(seconds=120)).isoformat(), "key": "k"}, {}),
            ({"at": (now + timedelta(seconds=120)).isoformat(), "about": "x"}, {}),
            ({"at": (now + timedelta(seconds=120)).isoformat(), "about": "x", "key": "k"}, {"status": "PARTIAL"}),
            ({"at": (now + timedelta(seconds=120)).isoformat(), "about": "x", "key": "k"}, {"used": 3}),
            ({"at": (now + timedelta(seconds=3600)).isoformat(), "about": "x", "key": "k"}, {}),
        ]
        for payload, kwargs in cases:
            code, out = self.later(payload, **kwargs)
            self.assertEqual(code, 0)
            self.assertIn("LATER_STATE=invalid", out, (payload, kwargs))
            self.assertFalse((self.dir / "later.json").exists())

    def test_ask_and_later_cannot_share_a_report(self):
        at = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
        (self.dir / "later-receipt.txt").write_text(
            "done\nSTATUS: DONE\n\n```agent-dispatch\n" + json.dumps(
                {"ask": ASK, "later": {"at": at, "about": "x", "key": "k"}}) + "\n```")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            RECEIPT.main(["later", "--dir", str(self.dir), "--deadline", str(int(time.time()) + 3600),
                          "--min-run", "60", "--used", "0", "--maximum", "3",
                          "--text-file", str(self.dir / "later-receipt.txt")])
        self.assertIn("LATER_STATE=invalid", out.getvalue())

    def test_first_answer_wins_and_then_links_the_continuation(self):
        self.parse(report(ASK))
        code, out = self.answer("2", "--by", ORIGIN)
        self.assertEqual(code, 0)
        self.assertIn("ANSWER_STATE=answering", out)
        self.assertIn("ANSWER_DEPTH=1", out)
        answer = json.loads((self.dir / "answer.json").read_text())
        self.assertEqual(answer["state"], "answering")
        self.assertEqual(answer["choice"], 2)
        self.assertEqual(answer["choice_text"], "方案乙")
        prompt = (self.dir / "answer-prompt.txt").read_text()
        self.assertIn("回答：方案乙", prompt)
        self.assertIn("不重做已完成的业务", prompt)
        with self.assertRaises(SystemExit) as caught:
            self.answer("1", "--by", ORIGIN)
        self.assertEqual(caught.exception.code, 3)
        self.assertEqual(json.loads((self.dir / "answer.json").read_text())["choice"], 2)
        self.assertEqual(RECEIPT.main(["finish-answer", "--dir", str(self.dir),
                                       "--task-id", "ask-task-answer-20260101-000001"]), 0)
        answer = json.loads((self.dir / "answer.json").read_text())
        self.assertEqual(answer["state"], "answered")
        self.assertEqual(answer["resume_task_id"], "ask-task-answer-20260101-000001")

    def test_wrong_source_cancelled_and_too_deep_are_refused(self):
        self.parse(report(ASK))
        with self.assertRaises(SystemExit) as caught:
            self.answer("1", "--by", "agent:main:other:direct:u2")
        self.assertEqual(caught.exception.code, 3)
        self.assertFalse((self.dir / "answer.json").exists())
        (self.dir / "result.env").write_text("STATE=cancelled\nOUTCOME=-\nSESSION=ses-1\n")
        with self.assertRaises(SystemExit) as caught:
            self.answer("1", "--by", ORIGIN)
        self.assertEqual(caught.exception.code, 3)
        (self.dir / "result.env").write_text("STATE=ok\nOUTCOME=DONE\nSESSION=ses-1\n")
        (self.dir / "meta.env").write_text(
            "ID=ask-task-20260101-000000\nAGENT=dsh\nNAME=ask-task\nCWD=/root\nNOTIFY=none\n"
            f"ORIGIN_SESSION={ORIGIN}\nANSWER_DEPTH=3\n")
        with self.assertRaises(SystemExit) as caught:
            self.answer("1", "--by", ORIGIN)
        self.assertEqual(caught.exception.code, 3)

    def test_resolve_only_closes_and_leaves_no_answer_task(self):
        self.parse(report(ASK))
        code, out = self.answer("--resolve", "--by", ORIGIN)
        self.assertEqual(code, 0)
        self.assertIn("ANSWER_STATE=resolved", out)
        answer = json.loads((self.dir / "answer.json").read_text())
        self.assertEqual(answer["state"], "resolved")
        self.assertFalse(answer["resume"])
        self.assertFalse((self.dir / "answer-prompt.txt").exists())

    def test_expired_question_needs_force_and_a_retry_can_replace_a_stale_claim(self):
        self.parse(report(ASK))
        question = json.loads((self.dir / "question.json").read_text())
        question["created_epoch"] = 0
        (self.dir / "question.json").chmod(0o644)
        (self.dir / "question.json").write_text(json.dumps(question))
        with self.assertRaises(SystemExit) as caught:
            self.answer("1", "--by", ORIGIN)
        self.assertEqual(caught.exception.code, 3)
        code, _ = self.answer("1", "--by", ORIGIN, "--force")
        self.assertEqual(code, 0)
        # A crash after O_EXCL leaves `answering`; it is retryable only once stale.
        (self.dir / "answer.json").chmod(0o644)
        (self.dir / "answer.json").write_text(json.dumps({"state": "answering", "choice": 1}))
        with self.assertRaises(SystemExit) as caught:
            self.answer("2", "--by", ORIGIN, "--force")
        self.assertEqual(caught.exception.code, 3)
        old = 1
        os.utime(self.dir / "answer.json", (old, old))
        code, _ = self.answer("2", "--by", ORIGIN, "--force")
        self.assertEqual(code, 0)
        self.assertEqual(stat.S_IMODE((self.dir / "answer.json").stat().st_mode), 0o444)


if __name__ == "__main__":
    unittest.main()
