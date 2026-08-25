"""The autonomous public broadcast must not rank active calls against passive holds.

rick_broadcast is sent straight to public Nostr relays. active calls and passive
stances are different claim types over different sample pools (decision_v2.compute_metrics
treats them separately), so declaring one "better" is an invalid read. Both renderers
used to flip their verdict on active_hit >= hold_hit; these tests pin that the copy
states non-comparability and never ranks, in either ordering.

Run: python3 -m pytest tests/test_rick_broadcast.py -q
"""
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops' / 'growth'))
import rick_broadcast

FORBIDDEN = ['less often', 'earned its keep', '还不如', '没拖后腿', 'this week', '这周']


def _card(active_hit, hold_hit):
    return {'active_hit': active_hit, 'active_n': 10, 'hold_hit': hold_hit, 'hold_n': 10,
            'high_conf_hit': 50, 'high_conf_n': 4, 'total_settled': 20}


def test_broadcast_never_ranks_active_vs_passive_in_either_ordering():
    for active_hit, hold_hit in ((20, 80), (80, 20)):
        s = _card(active_hit, hold_hit)
        for render, non_comparability in (
            (rick_broadcast.render_en, 'rank neither'),
            (rick_broadcast.render_zh, '不做高下排名'),
        ):
            out = render(s)
            # both rates still shown
            assert f'{active_hit}%' in out and f'{hold_hit}%' in out, out
            # the non-comparability statement is present
            assert non_comparability in out, out
            # and no ranking / windowed-time phrase survives
            for bad in FORBIDDEN:
                assert bad not in out, f'forbidden phrase {bad!r} in output:\n{out}'


def test_broadcast_is_explicitly_recommendation_only_and_python_graded():
    s = _card(40, 60)
    en = rick_broadcast.render_en(s)
    zh = rick_broadcast.render_zh(s)

    assert 'recommendation report card' in en
    assert 'directional hit rates, graded by Python' in en
    assert 'grading itself' not in en
    assert 'real money' not in en

    assert '建议成绩单' in zh
    assert 'Python 统计判断方向命中率' in zh
    assert '给自己打分' not in zh
    assert '真金白银' not in zh


def test_high_confidence_rate_is_active_only_and_renders_its_sample_size():
    representatives = [
        {'action': 'cut', 'confidence': 0.80, 'evaluation': {'outcome': 'win'}},
        {'action': 'cut', 'confidence': 0.60, 'evaluation': {'outcome': 'loss'}},
        {'action': 'hold_and_watch', 'confidence': 0.90,
         'evaluation': {'outcome': 'loss'}},
    ]
    with mock.patch.object(rick_broadcast.decision_v2, 'load_decisions', return_value=[]), \
         mock.patch.object(rick_broadcast.decision_v2, 'episode_representatives',
                           return_value=representatives):
        s = rick_broadcast.scorecard()

    assert s['high_conf_hit'] == 100
    assert s['high_conf_n'] == 1
    assert 'high-conviction active calls: 100% (n=1)' in rick_broadcast.render_en(s)
    assert '高信心主动判断:100%(n=1)' in rick_broadcast.render_zh(s)


# ---------------------------------------------------------------------------
# Broadcast-on-change gate (#978): the cron wrapper must not republish a
# byte-identical note. Asserted on invocation counts of stubbed executables,
# not on the script's text.
# ---------------------------------------------------------------------------

STUB_NODE = r'''#!/usr/bin/env bash
echo "$@" >> "$GATE_TEST_LOG"
if [[ -f "$GATE_TEST_NODE_FAIL" ]]; then exit 1; fi
exit 0
'''

STUB_PY = r'''#!/usr/bin/env bash
cat "$GATE_TEST_TEXT"
'''


def _run_wrapper(tmp_path, monkeypatch):
    """Copy ops/growth/rick_broadcast_nostr.sh into a sandbox, point its two
    host constants at the sandbox, and run it with stubbed python3/node."""
    import os
    import shutil
    import subprocess
    import textwrap

    src = ROOT / 'ops' / 'growth' / 'rick_broadcast_nostr.sh'
    script = tmp_path / 'wrapper.sh'
    body = src.read_text(encoding='utf-8')
    # The sandbox replaces exactly the two literals the coupling ratchet pins.
    body = body.replace('cd /root/.openclaw/workspace', f'cd "{tmp_path}/ws"')
    body = body.replace('KEYFILE=/root/.openclaw/nostr-rick.key',
                        f'KEYFILE="{tmp_path}/nostr-rick.key"')
    assert '/root/.openclaw' not in body, 'sandbox copy must not touch real host paths'
    script.write_text(body, encoding='utf-8')
    script.chmod(0o755)

    (tmp_path / 'ws').mkdir(exist_ok=True)
    (tmp_path / 'ws' / 'ops' / 'growth').mkdir(parents=True, exist_ok=True)
    shutil.copy(src.parent / 'rick_broadcast.py',
                tmp_path / 'ws' / 'ops' / 'growth' / 'rick_broadcast.py')
    (tmp_path / 'nostr-rick.key').write_text('nsec-gate-test-only', encoding='utf-8')

    log = tmp_path / 'calls.log'
    log.write_text('', encoding='utf-8')
    fail_flag = tmp_path / 'make-node-fail'
    text_file = tmp_path / 'post.txt'
    text_file.write_text('scorecard v1', encoding='utf-8')

    stubs = tmp_path / 'stubs'
    stubs.mkdir()
    for name, body_ in (('node', STUB_NODE), ('python3', STUB_PY)):
        p = stubs / name
        p.write_text(body_, encoding='utf-8')
        p.chmod(0o755)

    env = dict(os.environ)
    env['PATH'] = f'{stubs}:{env["PATH"]}'
    env['GATE_TEST_LOG'] = str(log)
    env['GATE_TEST_NODE_FAIL'] = str(fail_flag)
    env['GATE_TEST_TEXT'] = str(text_file)

    def run():
        return subprocess.run(['bash', str(script)], env=env,
                              capture_output=True, text=True)

    return run, log, fail_flag, text_file


def test_wrapper_skips_a_byte_identical_republish_and_publishes_changes(tmp_path, monkeypatch):
    import subprocess
    run, log, fail_flag, text_file = _run_wrapper(tmp_path, monkeypatch)

    first = run()
    assert first.returncode == 0, first.stderr
    assert len(log.read_text().splitlines()) == 1  # python3 + node → node called once

    second = run()  # same scorecard text: the duplicate is skipped
    assert second.returncode == 0, second.stderr
    assert len(log.read_text().splitlines()) == 1, (
        'an unchanged scorecard must not reach the publisher again')

    text_file.write_text('scorecard v2 — settled 10 new', encoding='utf-8')
    third = run()
    assert third.returncode == 0, third.stderr
    assert len(log.read_text().splitlines()) == 2, (
        'changed scorecard text must publish')


def test_wrapper_state_only_advances_after_a_confirmed_publish(tmp_path, monkeypatch):
    import subprocess
    run, log, fail_flag, text_file = _run_wrapper(tmp_path, monkeypatch)

    assert run().returncode == 0
    state = tmp_path / 'ws' / 'logs' / 'nostr_last_post.sha256'
    digest_after_ok = state.read_text().strip()

    text_file.write_text('scorecard v2', encoding='utf-8')
    fail_flag.write_text('x', encoding='utf-8')  # relays reject everything
    failed = run()
    assert failed.returncode != 0
    assert state.read_text().strip() == digest_after_ok, (
        'a failed publish must not record its digest as published')

    fail_flag.unlink()  # relays recover: the unpublished text retries next night
    retried = run()
    assert retried.returncode == 0, retried.stderr
    assert len(log.read_text().splitlines()) == 3
    assert state.read_text().strip() != digest_after_ok

