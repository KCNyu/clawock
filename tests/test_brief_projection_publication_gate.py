"""A green brief may not publish while its Pages projection stays stale."""
from __future__ import annotations

import json
import sys
from datetime import datetime

from clawock.harness import brief_postflight as postflight


def _filled_judgment(generation_id="generation-fixture", tickers=()):
    """A judgment that passes validation, so postflight's gap check stays quiet.

    Since #1232 the report is rendered from the judgment, so an absent one is a
    reported issue (`_judgment_gap_issues`). These fixtures are about the plan
    and publication paths, not about that check, and they should not go quiet by
    accident.
    """
    from clawock.decision.packet import judgment_template

    overlay = judgment_template({
        "_meta": {"generation_id": generation_id},
        "tickers": {ticker: {} for ticker in tickers},
    })
    overlay["portfolio_assessment"] = "fixture assessment"
    overlay["portfolio_counterargument"] = "fixture counterargument"
    for field, value in list(overlay["narrative"].items()):
        if field == "risk_voice_first":
            continue
        overlay["narrative"][field] = (
            ["fixture step"] if isinstance(value, list) else "fixture text")
    for row in overlay["ticker_judgments"]:
        for field, value in list(row.items()):
            if value == "":
                row[field] = "fixture text"
    return overlay


def _run_postflight(tmp_path, monkeypatch, capsys, *, projection_error=None):
    today = datetime.now().strftime('%Y-%m-%d')
    context_path = tmp_path / 'memory' / '.tmp' / f'brief-context-{today}.json'
    context_path.parent.mkdir(parents=True)
    context_path.write_text(json.dumps({'generation_id': 'generation-fixture'}))
    (context_path.parent / f'brief-judgment-{today}.json').write_text(
        json.dumps(_filled_judgment(), ensure_ascii=False))

    stages = []
    commits = []
    monkeypatch.setattr(postflight, 'WS', tmp_path)
    monkeypatch.setattr(
        postflight.trading_calendar, 'closed_reason', lambda _market: None
    )
    monkeypatch.setattr(
        postflight.workflow_outcomes, 'slot_for_job', lambda _job: 'slot'
    )
    monkeypatch.setattr(
        postflight.workflow_outcomes,
        'record_stage',
        lambda job, stage, state, **fields: stages.append(
            (job, stage, state, fields)
        ),
    )
    monkeypatch.setattr(
        postflight.brief_context, 'validate_run_bundle', lambda *_args: []
    )
    monkeypatch.setattr(
        postflight.brief_decision_packet,
        'read_packet',
        lambda _manifest: {'_meta': {'generation_id': 'generation-fixture'}},
    )
    monkeypatch.setattr(postflight, 'validate_markdown', lambda *_a, **_k: [])
    monkeypatch.setattr(
        postflight, 'readability_issues', lambda _readability: []
    )
    monkeypatch.setattr(
        postflight,
        'normalize_plan_json',
        lambda *_a, **_k: ([], {'decisions': []}),
    )
    monkeypatch.setattr(postflight, 'validate_plan_json', lambda *_a, **_k: [])
    monkeypatch.setattr(postflight, 'already_delivered', lambda _path: True)

    def maybe_commit(status, _today, dry_run=False):
        commits.append((status, dry_run))
        return ((True, 'committed + pushed') if status != 'fail'
                else (False, 'skipped (status=fail)'))

    monkeypatch.setattr(postflight, 'maybe_commit', maybe_commit)
    monkeypatch.setattr(
        postflight, 'dashboard_publication_state', lambda _ws: 'published'
    )

    if projection_error:
        def write_projection(*_args):
            raise RuntimeError(projection_error)
    else:
        def write_projection(_packet, _judgment, output):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text('{}')
            return {'judgment_status': 'missing'}, []
    monkeypatch.setattr(
        postflight.brief_decision_packet,
        'write_pages_projection',
        write_projection,
    )
    monkeypatch.setattr(sys, 'argv', ['brief_postflight.py'])

    code = postflight.main()
    result = json.loads(capsys.readouterr().out)
    gate = json.loads(
        (tmp_path / 'logs' / 'brief_postflight_status.json').read_text()
    )
    return code, result, gate, commits, stages


def test_projection_failure_keeps_publish_gate_closed_and_fails_stage(
    tmp_path, monkeypatch, capsys
):
    code, result, gate, commits, stages = _run_postflight(
        tmp_path, monkeypatch, capsys, projection_error='disk full'
    )

    assert code == 2
    assert result['status'] == 'pass'
    assert result['projection_status'] == 'failed'
    assert result['projection_issues'] == ['disk full']
    assert result['publication_ready'] is False
    assert commits == [('fail', False)]
    assert gate['publish_ok'] is False
    assert gate['reason'] == 'pages_projection_failed'
    assert next(state for _, stage, state, _ in stages
                if stage == 'postflight') == 'failed'


def test_written_deterministic_projection_releases_existing_publish_route(
    tmp_path, monkeypatch, capsys
):
    code, result, gate, commits, stages = _run_postflight(
        tmp_path, monkeypatch, capsys
    )

    assert code == 0
    assert result['projection_status'] == 'missing'
    assert result['publication_ready'] is True
    assert commits == [('pass', False)]
    assert gate['publish_ok'] is True
    assert 'reason' not in gate
    assert next(state for _, stage, state, _ in stages
                if stage == 'postflight') == 'success'
