"""The synthetic benefit fixture must prove the note layer adds what the injected
index does not, and must not manufacture hits for absent questions."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "ops/host/shared-memory-eval/benefit/run_benefit.py"


def test_fixture_separates_the_index_from_the_note_layer(tmp_path):
    out = tmp_path / "benefit.json"
    proc = subprocess.run([sys.executable, str(RUNNER), "--json", str(out)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    modes = json.loads(out.read_text())
    assert modes["none"]["hits"] == 0
    assert modes["index"]["hits"] == 0
    assert (modes["search"]["positives"], modes["search"]["hits"]) == (8, 8)
    assert modes["search"]["avg_rank"] == 1.0
    assert modes["search"]["negatives"] == 2
    assert modes["search"]["false_positives"] == 0
    assert modes["search"]["misses"] == []
