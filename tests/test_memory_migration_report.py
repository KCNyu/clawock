import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_migration_report_counts_legacy_and_light_without_exposing_contents(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    memory = tmp_path / "memory"
    light = memory / "dreaming/light"
    light.mkdir(parents=True)
    lesson = "Check source identity before trusting generated output."
    private = "The deployment reference points to /srv/private-desk."
    legacy = memory / "legacy.md"
    legacy.write_text(f"# Note\n\n{lesson}\n\n{private}\n")
    (memory / "2026-01-01-pre-open.md").write_text("Existing brief excluded from the audit.")
    (light / "dream.md").write_text(lesson + "\n\nUse 12 records to establish a baseline.")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "ops/host/memory_migration_report.py"),
         "--workspace", str(tmp_path), "--store", str(store)],
        check=True, capture_output=True, text=True,
    )

    report = json.loads(proc.stdout)
    assert report["files"] == {"legacy": 1, "light": 1}
    assert report["counts"] == {"extractable": 1, "duplicate": 1, "discard": 2}
    assert {row["reason"] for row in report["candidates"]} == {
        "screened_for_review", "protected_or_transient", "normalized_text_match", "no_ledger_binding",
    }
    assert private not in proc.stdout
    assert lesson not in proc.stdout
    assert legacy.read_text() == f"# Note\n\n{lesson}\n\n{private}\n"
