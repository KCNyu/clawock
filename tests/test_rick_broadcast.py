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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))
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
