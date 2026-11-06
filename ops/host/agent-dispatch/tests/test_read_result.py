import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("read_result", Path(__file__).parents[1] / "read-result.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ResultTests(unittest.TestCase):
    def test_claude_numeric_latest_and_incomplete_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "attempt9.json").write_text(json.dumps({"result": "older"}))
            (root / "attempt10.json").write_text(json.dumps({"result": "latest\nSTATUS: DONE"}))
            self.assertEqual(module.read_result(root), "latest\nSTATUS: DONE")
            (root / "attempt11.json").write_text("")
            with self.assertRaises(ValueError):
                module.read_result(root)

    def test_codex_ignores_tool_output_and_uses_last_assistant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {"type": "item.completed", "item": {"type": "agent_message", "text": "working"}},
                {"type": "item.completed", "item": {"type": "command_execution", "text": "irrelevant"}},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "done\nSTATUS: DONE"}},
                {"type": "turn.completed"},
            ]
            (root / "attempt1.jsonl").write_text("\n".join(map(json.dumps, events)))
            self.assertEqual(module.read_result(root), "done\nSTATUS: DONE")

    def test_opencode_last_message_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [{"type": "text", "part": {"messageID": mid, "text": text}}
                      for mid, text in [("a", "working"), ("b", "done\n"), ("b", "STATUS: DONE")]]
            events.append({"type": "step_finish", "part": {"reason": "stop"}})
            (root / "attempt1.jsonl").write_text("\n".join(map(json.dumps, events)))
            self.assertEqual(module.read_result(root), "done\nSTATUS: DONE")

    def test_dsh_final_message_of_a_completed_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = [{"type": "session", "sessionId": "session-1", "cwd": "/root"},
                    {"type": "text", "text": "working"},
                    {"type": "tool_result", "callId": "c1", "status": "completed", "result": "STATUS: DONE"}]
            done = [{"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "completed"}},
                    {"type": "final", "text": "done\nSTATUS: DONE"}]
            (root / "attempt1.jsonl").write_text("\n".join(map(json.dumps, head + done)))
            (root / "attempt1.yml").write_text("- id: agent-default-model\n")
            self.assertEqual(module.read_result(root), "done\nSTATUS: DONE")
            failed = [{"type": "status", "phase": "turn_end", "turn": 1,
                       "reason": {"kind": "error", "error": {"code": "QUOTA", "message": "Insufficient Balance"}}},
                      {"type": "final", "text": ""}]
            (root / "attempt2.jsonl").write_text("\n".join(map(json.dumps, head + failed)))
            with self.assertRaises(ValueError):
                module.read_result(root)

    def test_report_prints_the_question_and_one_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "task-1"
            root.mkdir()
            (root / "attempt1.json").write_text(json.dumps({"result": "done\nSTATUS: DONE"}))
            (root / "meta.env").write_text("ID=task-1\nNOTIFY=none\n")
            (root / "result.env").write_text("STATE=ok\nOUTCOME=DONE\n")
            (root / "question.json").write_text(json.dumps({
                "state": "open", "key": "pick", "asked_by_run": 1, "title": "选一个",
                "options": ["甲", "乙"]}))
            text = module.report(root)
            self.assertIn("question: open key=pick asked_by_run=1", text)
            self.assertIn("question_option_2: 乙", text)
            self.assertIn("answer_command: dispatch.sh answer task-1 <n>", text)
            (root / "answer.json").write_text(json.dumps({
                "state": "answered", "choice": 2, "choice_text": "乙",
                "answered_by": "agent:main:x:direct:y", "answered_at": "2026-01-01 00:00:00",
                "resume_task_id": "task-1-answer"}))
            text = module.report(root)
            self.assertIn("answer: choice=2 text=乙", text)
            self.assertIn("resumed_as=task-1-answer", text)

    def test_interrupted_codex_commentary_is_not_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "attempt1.jsonl").write_text(json.dumps({
                "type": "item.completed", "item": {"type": "agent_message", "text": "working"}}))
            with self.assertRaises(ValueError):
                module.read_result(root)


if __name__ == "__main__":
    unittest.main()
