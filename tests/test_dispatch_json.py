"""The dispatch control files have one tolerant reader (#3483)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "ops" / "host" / "agent-dispatch"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reader_contract_is_unreadable_or_non_object_to_empty(tmp_path):
    module = _load(DISPATCH / "dispatch_json.py", "dispatch_json_contract")
    assert module.read_json_object(tmp_path / "missing.json") == {}
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert module.read_json_object(tmp_path / "broken.json") == {}
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    assert module.read_json_object(tmp_path / "list.json") == {}
    (tmp_path / "object.json").write_text('{"a": 1}', encoding="utf-8")
    assert module.read_json_object(tmp_path / "object.json") == {"a": 1}


def test_the_three_entry_points_share_the_owner():
    for name in ("read-result.py", "receipt.py"):
        source = (DISPATCH / name).read_text(encoding="utf-8")
        assert "def read_json(" not in source, name
        assert "from dispatch_json import read_json_object" in source, name
    queue = (ROOT / "ops" / "host" / "task_queue_ops.py").read_text(encoding="utf-8")
    assert "def _read_json_file(" not in queue
    assert "from dispatch_json import read_json_object" in queue


def test_task_queue_ops_finds_the_owner_from_the_checkout_layout():
    result = subprocess.run(
        [sys.executable, str(ROOT / "ops" / "host" / "task_queue_ops.py"), "version"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("(api 3)")
