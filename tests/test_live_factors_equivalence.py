"""The mounted `factors` plugin against the implementation it took over from.

`decision.signals.compute_signals` now answers from the plugin. The arithmetic
it used to run is still in the module as `legacy_*`, and this file is why it is
still there: the two must agree exactly, floats included, before the legacy
copy can be removed. Every prefix of every stored series is compared, so each
branch the live paths can reach on this book — too short, short-history, no
MA200 yet, each setup firing — is one of the cases.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from clawock.decision import signals
from clawock.strategies import live
from clawock.strategies.plugins import quant_factors

BARS = sorted((Path(__file__).resolve().parents[1] / 'memory' / 'bars').glob('*.json'))


def _stored(path):
    doc = json.loads(path.read_text(encoding='utf-8'))
    return [dict(bar, date=day) for day, bar in sorted(doc['bars'].items())]


def _walk(seed, sessions):
    rnd = random.Random(seed)
    close, rows = 100.0, []
    for day in range(sessions):
        previous = close
        close *= 1 + rnd.gauss(0.0005, 0.03)
        high, low = max(previous, close) * (1 + rnd.random() * 0.02), min(previous, close) * (1 - rnd.random() * 0.02)
        rows.append({'date': f'd{day:04d}', 'open': previous, 'high': high, 'low': low, 'close': close})
    # Rows the cleaner must drop the same way on both sides.
    rows.insert(sessions // 2, {'date': 'bad', 'open': 1, 'high': 1, 'low': 1, 'close': 0})
    rows.insert(sessions // 3, {'date': 'bad2', 'open': None, 'high': 1, 'low': 1, 'close': 1})
    return rows


def _same_on_every_prefix(rows):
    factors, fired = live.service('factors'), set()
    for end in range(len(rows) + 1):
        prefix = rows[:end]
        mature = signals.legacy_compute_signals(prefix)
        assert factors.signals(prefix) == mature
        assert signals.compute_signals(prefix) == mature
        short = signals.legacy_compute_short_history_signals(prefix)
        assert factors.short_history(prefix) == short
        assert signals.compute_short_history_signals(prefix) == short
        fired.update(setup['setup_id'] for setup in (mature or {}).get('technical_setups', []))
    return fired


def test_the_store_is_there_to_compare():
    assert len(BARS) >= 20


@pytest.mark.parametrize('path', BARS, ids=lambda path: path.stem)
def test_plugin_and_legacy_agree_on_every_prefix_of_a_stored_series(path):
    _same_on_every_prefix(_stored(path))


def test_plugin_and_legacy_agree_on_long_generated_series_where_every_setup_fires():
    fired = set()
    for seed in range(6):
        fired |= _same_on_every_prefix(_walk(seed, 420))
    # 420 sessions reach MA200 and the 12-1 momentum, which the store's short
    # series do not; and the comparison saw each setup actually produced.
    assert fired == {'trend_pullback', 'confirmed_breakout', 'oversold_reclaim'}


def test_the_helpers_agree():
    factors = live.service('factors')
    for seed in range(4):
        rows = [row for row in _walk(seed, 80) if not row['date'].startswith('bad')]
        closes = [row['close'] for row in rows]
        for end in range(len(rows) + 1):
            for period in (5, 14, 28):
                assert factors.rsi(closes[:end], period) == signals._rsi14(closes[:end], period)
                assert factors.atr(rows[:end], period) == signals._atr14(rows[:end], period)


def test_the_registered_volatility_target_is_the_one_the_module_always_used():
    assert quant_factors.SIGMA_TARGET == signals.SIGMA_TARGET == 0.25
    assert live.service('factors').describe() == {'sigma_target': signals.SIGMA_TARGET}
