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
