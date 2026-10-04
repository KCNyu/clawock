"""The weekly review index lists weeks, not files.

`memory/weekly/` is missing 2026-W33 and 2026-W35: both scheduled runs failed
(31952091127, 33326401496 — three `timeout after 180s` on the primary against a
fallback answering 401), and nothing re-runs a scheduled workflow. The site's
Weekly Reviews list rendered `site.pages`, so a week that was never written
simply was not there. The middle gap was a jump in the numbers nobody reads;
the trailing gap had nothing after it to look wrong beside.

So `stage_site.weekly_index` computes the span the series *should* cover and
marks each week present or not. This file pins the three cases that make the
computation worth having over the old file listing.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "pages"))
sys.path.insert(0, str(ROOT / "src"))

import stage_site  # noqa: E402

from clawock.automation import llm  # noqa: E402


def _tree(tmp_path, weeks):
    directory = tmp_path / "memory" / "weekly"
    directory.mkdir(parents=True)
    for week in weeks:
        (directory / f"{week}.md").write_text("---\nlayout: default\n---\n", encoding="utf-8")
    return tmp_path


def _weeks(rows):
    return [(row["week"], row["present"]) for row in rows]


def test_a_gap_between_two_reviews_is_named(tmp_path):
    root = _tree(tmp_path, ["2026-W32", "2026-W34"])
    rows = stage_site.weekly_index(root, now=datetime(2026, 8, 25, tzinfo=timezone.utc))
    assert _weeks(rows) == [
        ("2026-W34", True),
        ("2026-W33", False),
        ("2026-W32", True),
    ]


def test_a_trailing_gap_is_named_too(tmp_path):
    """The case a file listing cannot show: the series just stops.

    2026-W35's fire was Sunday 2026-08-30 14:00 UTC. By the following Friday it
    is long past due, and the newest file is still 2026-W34.
    """
    root = _tree(tmp_path, ["2026-W34"])
    rows = stage_site.weekly_index(root, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
    assert _weeks(rows) == [("2026-W35", False), ("2026-W34", True)]


def test_a_week_whose_fire_has_not_landed_yet_is_not_called_missing(tmp_path):
    """Sunday 15:00 UTC is one hour after the cron and inside its drift.

    The 2026-08-30 run started 3.8 hours late; announcing a missing review at
    the first minute past the schedule would put a false hole on the page every
    Sunday evening.
    """
    root = _tree(tmp_path, ["2026-W35"])
    rows = stage_site.weekly_index(root, now=datetime(2026, 9, 6, 15, tzinfo=timezone.utc))
    assert _weeks(rows) == [("2026-W35", True)]


def test_the_span_crosses_a_year_boundary_by_the_calendar(tmp_path):
    """2026 has 53 ISO weeks; 2027 starts at W01 four days into January."""
    root = _tree(tmp_path, ["2026-W52"])
    rows = stage_site.weekly_index(root, now=datetime(2027, 1, 15, tzinfo=timezone.utc))
    assert _weeks(rows) == [
        ("2027-W01", False),
        ("2026-W53", False),
        ("2026-W52", True),
    ]


def test_staging_hands_the_index_to_jekyll(tmp_path):
    output = tmp_path / "site-source"
    subprocess.run(
        ["python3", str(ROOT / "ops/pages/stage_site.py"), "--output-dir", str(output)],
        cwd=ROOT,
        check=True,
    )
    rows = yaml.safe_load(
        (output / "_data" / "weekly_reviews.yml").read_text(encoding="utf-8")
    )
    assert rows and isinstance(rows, list)
    # Every row the page renders has to be answerable from this file alone, and
    # `present` has to survive as a boolean rather than the string "false".
    for row in rows:
        assert set(row) == {"week", "present", "path"}, row
        assert isinstance(row["present"], bool), row
    assert rows[0]["week"] > rows[-1]["week"], "newest first"


def test_the_page_reads_the_index_rather_than_the_file_listing():
    page = (ROOT / "site" / "briefs.md").read_text(encoding="utf-8")
    weekly = page.split("## Weekly Reviews")[1]
    assert "site.data.weekly_reviews" in weekly, (
        "the weekly list is back to rendering whatever files exist, which is "
        "exactly the rendering that hid 2026-W33 and 2026-W35")


def test_the_page_names_the_provider_the_code_actually_calls():
    """It advertised `Xiaomi MiMo v2.5-pro` for months after that key died.

    The primary moved to MiniMax M3 and, until 2026-09-13, the fallback was
    OpenCode Zen (#695, #697) — removed when its wallet had been empty for
    weeks. A public page describing a provider the code no longer calls is a
    wrong fact in front of every reader, and nothing was comparing the sentence
    to the constant it describes.
    """
    page = (ROOT / "site" / "briefs.md").read_text(encoding="utf-8")
    weekly = page.split("## Weekly Reviews")[1].split("##")[0]
    assert llm.MINIMAX_MODEL in weekly, (
        f"the weekly section does not name {llm.MINIMAX_MODEL}: {weekly[:300]}")
    for dead in ("Xiaomi", "MiMo", "OpenCode", "deepseek"):
        assert dead not in weekly, (
            f"the weekly section still advertises the removed {dead} route")


def test_operational_health_reports_the_same_due_gaps(tmp_path, monkeypatch, capsys):
    from clawock.automation.weekly_health import missing_weeks
    import importlib.util
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    health = load('weekly_workflow_health', 'ops/ci/workflow_health.py')
    system = load('weekly_system_check', 'ops/system_check.py')
    root = _tree(tmp_path, ['2026-W32', '2026-W34'])
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    assert missing_weeks(root, now=now) == ['2026-W33']
    workflows = root / '.github' / 'workflows'
    workflows.mkdir(parents=True)
    (workflows / 'weekly-review.yml').write_text("cron: '0 14 * * 0'\n")
    monkeypatch.setattr(health, 'fetch_runs', lambda *a, **kw: [dict(
        event='schedule', status='completed', conclusion='success',
        createdAt='2026-08-23T14:00:00Z')])
    result = health.report(now=now, workflow_dir=workflows, source_root=root)
    row = result['workflows'][0]
    assert row['status'] == 'attention'
    assert row['missing_weeks'] == ['2026-W33']
    health._surface(result)
    assert 'missing due reviews: 2026-W33' in capsys.readouterr().out
    monkeypatch.setattr(system, 'WS', root)
    class Recorder:
        def add(self, *args):
            self.row = args
    recorder = Recorder()
    system.check_weekly_reviews(recorder, now=now)
    assert recorder.row[1] == system.WARNING
    assert '2026-W33' in recorder.row[2]
    (root / 'memory/weekly/2026-W33.md').write_text('review')
    system.check_weekly_reviews(recorder, now=now)
    assert recorder.row[1] == system.OK
