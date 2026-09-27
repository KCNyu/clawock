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

    def test_interrupted_codex_commentary_is_not_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "attempt1.jsonl").write_text(json.dumps({
                "type": "item.completed", "item": {"type": "agent_message", "text": "working"}}))
            with self.assertRaises(ValueError):
                module.read_result(root)


if __name__ == "__main__":
    unittest.main()
