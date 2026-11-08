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


def test_answer_outside_returned_recall_does_not_count_as_a_hit(tmp_path):
    store = tmp_path / 'store'
    store.mkdir()
    (store / 'MEMORY.md').write_text('# Index\n- `feedback-probe.md` — probe\n')
    (store / 'feedback-probe.md').write_text(
        '---\nname: feedback-probe\ndescription: probe\n---\n\n'
        + 'probe match without answer\n' * 10 + '\nTHE_UNRETURNED_ANSWER\n')
    cases = tmp_path / 'cases.tsv'
    cases.write_text('hidden\tprobe\tfeedback-probe.md\tTHE_UNRETURNED_ANSWER\tpositive\n')
    out = tmp_path / 'result.json'
    proc = subprocess.run([sys.executable, str(RUNNER), '--store', str(store), '--cases', str(cases),
                           '--json', str(out)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(out.read_text())['search']
    assert result['rows'][0]['rank'] == 1, 'topic retrieval succeeds'
    assert result['hits'] == 0, 'a topic hit is not evidence that the answer was returned'
