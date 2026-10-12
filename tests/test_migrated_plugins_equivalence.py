"""The migrated plugins against the code they took over from.

`tests/legacy_shadow.py` compares every call the suite makes into a migrated
plugin with the same call into its `legacy_*` module. This file is the part of
that comparison that does not depend on what other tests happen to call:

* the shadow is armed for all eight pairs, and reports each kind of departure
  it claims to (checked on a pair of modules built for the purpose);
* the import paths the readers use are the mounted plugins;
* the plugins are driven over this book's stored bars, policies and holdings,
  so the comparison has run on real inputs whatever else the suite does.
"""
from __future__ import annotations

import importlib
import json
import random
import types
from pathlib import Path

import pytest

import legacy_shadow
from clawock.decision import (
    add_alpha, add_policy, add_side, intraday_policy, left_side, preposition, signals)
from clawock.evaluation import signal_panel
from clawock.market_data import bar_signals
from clawock.plugin_host import live

ROOT = Path(__file__).resolve().parents[1]
BARS = sorted((ROOT / 'memory' / 'bars').glob('*.json'))
FACADES = {'add_policy': add_policy, 'add_alpha': add_alpha, 'left_side': left_side,
           'add_side': add_side, 'preposition': preposition,
           'intraday_policy': intraday_policy, 'bar_signals': bar_signals,
           'signal_panel': signal_panel}


def _stored(path):
    doc = json.loads(path.read_text(encoding='utf-8'))
    return [dict(bar, date=day) for day, bar in sorted(doc['bars'].items())]


def _calls(label):
    return legacy_shadow.compared.get(label, 0)


@pytest.fixture
def departures():
    """What the shadow collected during the test; emptied so the test can assert on it."""
    def take():
        seen = list(legacy_shadow.mismatches)
        del legacy_shadow.mismatches[:]
        return seen
    return take


def _pair(plugin_source, legacy_source):
    plugin, legacy = types.ModuleType('shadow_demo_plugin'), types.ModuleType('shadow_demo_legacy')
    exec(plugin_source, vars(plugin))
    exec(legacy_source, vars(legacy))
    for module in (plugin, legacy):
        for value in vars(module).values():
            if isinstance(value, types.FunctionType):
                value.__module__ = module.__name__
    return legacy_shadow._wrap(plugin, legacy, 'answer', dict(vars(plugin))), plugin


SAME = 'LIMIT = 2\ndef answer(rows, fetch=None):\n    rows.append(len(rows))\n    return [fetch(r) if fetch else r * LIMIT for r in rows]\n'


@pytest.mark.parametrize('legacy_source, said', [
    (SAME, None),
    (SAME.replace('r * LIMIT', 'r * LIMIT + 1e-12'), 'plugin value'),
    (SAME.replace('    rows.append(len(rows))\n', ''), 'plugin value'),
    (SAME.replace('    return', '    out =').rstrip('\n') + '\n    rows.append(0.5)\n    return out\n',
     'different states'),
    (SAME.replace('    return', '    raise KeyError("gone")\n    return'), 'legacy error'),
], ids=['same', 'last-digit', 'argument-not-touched', 'argument-left-different', 'raises'])
def test_the_shadow_reports_a_different_value_error_or_argument_state(
        legacy_source, said, departures):
    answer, _ = _pair(SAME, legacy_source)
    assert answer([1.5, 2.5]) == [3.0, 5.0, 4]
    seen = departures()
    assert (seen == []) if said is None else (len(seen) == 1 and said in seen[0])


def test_a_callback_is_called_once_and_a_patched_global_reaches_both_sides(departures):
    answer, plugin = _pair(SAME, SAME)
    asked = []

    def fetch(row):
        asked.append(row)
        return row + 1
    assert answer([1], fetch=fetch) == [2, 2]
    assert asked == [1, 1] and departures() == []

    stray, _ = _pair(SAME, SAME.replace('fetch(r) if fetch', 'fetch(r + 100) if fetch'))
    stray([1], fetch=fetch)
    assert 'never asked' in departures()[0]

    plugin.LIMIT = 10
    assert answer([1]) == [10, 10] and departures() == []


def test_every_pair_is_armed_and_the_readers_import_paths_are_the_mounted_plugins(departures):
    for plugin_name, legacy_name in legacy_shadow.PAIRS:
        plugin = importlib.import_module(plugin_name)
        service = plugin_name.rsplit('.', 1)[1]
        assert live.service(service) is plugin
        wrapped = [name for name, value in vars(plugin).items()
                   if isinstance(value, types.FunctionType) and hasattr(value, '__wrapped__')
                   and value.__wrapped__.__module__ == plugin_name]
        assert wrapped, plugin_name
        legacy = importlib.import_module(legacy_name)
        for name in wrapped:
            assert getattr(legacy, name).__module__ == legacy_name
            # The reader's import path answers with the plugin's function.
            assert getattr(FACADES[service], name) is getattr(plugin, name)
    # A real pair, made to disagree: the helper under the legacy estimators is replaced.
    rows = _stored(BARS[0])
    legacy = importlib.import_module('clawock.market_data.legacy_bar_signals')
    kept = legacy._returns
    legacy._returns = lambda *a, **k: []
    try:
        bar_signals.realised_moments(rows, len(rows) - 1)
    finally:
        legacy._returns = kept
    assert 'bar_signals.realised_moments' in departures()[0]


@pytest.mark.parametrize('path', BARS, ids=lambda path: path.stem)
def test_the_plugins_agree_with_legacy_over_a_stored_series(path, departures):
    rows = _stored(path)
    before = {label: _calls(label) for label in (
        'bar_signals.bar_signal_row', 'add_side.radar', 'left_side.ladder',
        'add_alpha.confirmation_levels', 'left_side.scale_in_setup')}
    policy = json.loads((ROOT / 'config' / 'add-alpha-policy.json').read_text())
    params = add_policy.read_params(policy)
    left = left_side.load_policy()
    by_index = {}
    # Volume is not in the settled store; a generated one keeps Amihud and the
    # volume ratio on a path where they return numbers.
    priced = [dict(row, volume=1e6 * (1 + (i * 7919) % 13)) for i, row in enumerate(rows)]
    for index in sorted({*range(0, len(rows), 9), *range(max(0, len(rows) - 12), len(rows))}):
        by_index[index] = bar_signals.bar_signal_row(priced, index)
    assert bar_signals.availability({path.stem: by_index[len(rows) - 1]})
    for end in range(20, len(rows) + 1, 3):
        row = signals.compute_signals(rows[:end]) or signals.compute_short_history_signals(rows[:end])
        if not row:
            continue
        for at_close in (True, False):
            add_side.radar({path.stem: row}, near_pct=params['near_pct'],
                           no_chase_z=params['no_chase_z'], confirmed_at_close=at_close,
                           left_policy=left, holdings_of={path.stem: [path.stem]})
        add_side.daily_radar({path.stem: row}, near_pct=params['near_pct'],
                             no_chase_z=params['no_chase_z'])
        add_alpha.confirmation_levels(row)
        left_side.ladder(row, left)
        for leveraged in (False, True):
            left_side.scale_in_setup(row, left, ticker=path.stem, market='US',
                                     leveraged=leveraged, used_tranches=end % 3)
            for thesis in (None, 'intact', 'damaged'):
                left_side.observe(row, left, leveraged=leveraged, thesis_state=thesis,
                                  blockers=('negative_information',) if end % 2 else ())
    assert departures() == []
    for label, count in before.items():
        if label != 'bar_signals.bar_signal_row' and len(rows) < 20:
            continue
        assert _calls(label) > count, label


def test_sizing_agrees_with_legacy_across_tiers_prices_and_room(departures):
    policy = json.loads((ROOT / 'config' / 'add-alpha-policy.json').read_text())
    experiment = json.loads((ROOT / 'config' / 'preposition-policy.json').read_text())
    rnd, before = random.Random(11), _calls('add_policy.tranche_plan')
    for tier in (*add_policy.AUTHORISED_TIERS, 'left_scale_in', 'observe', None):
        add_policy.is_authorised_tier(tier)
        for _ in range(40):
            # A refusal is an outcome too: the shadow holds legacy to the same error.
            try:
                add_policy.tier_terms(policy, tier, experiment_policy=experiment)
                add_policy.tranche_plan(
                    tier=tier or 'validated', price=rnd.choice([None, 0.0, 3.21, 87.5, 912.0]),
                    lot=rnd.choice([None, 1, 100, 500]), shares=rnd.choice([0, 100, 2500]),
                    current_value=rnd.choice([None, 0.0, 4e4, 9e5]),
                    capital=rnd.choice([0.0, 5e4, 3e5, 2e6]),
                    cash=rnd.choice([0.0, 1e3, 8e4, 1e6]),
                    setup_pcts=rnd.choice([[], [0.0125], [0.025, 0.0125], [0.05]]),
                    sizing_multiplier=rnd.choice([1.0, 0.5, 0.0]),
                    policy=rnd.choice([policy, None, {}]),
                    setup_tiers=rnd.choice(
                        [None, ['validated'], ['exploration', 'user_experiment']]),
                    stop_distance=rnd.choice([None, 0.04, 0.18]), leveraged=rnd.random() < 0.3)
            except Exception:
                pass
    for entry in add_policy.ENTRY_PROFILES:
        add_policy.entry_profile(entry)
    for candidate in (policy, None, {}, {'exploration_tranche_pct': 0}):
        add_policy.read_params(candidate)
        add_policy.size_cap_text(candidate)
    assert departures() == [] and _calls('add_policy.tranche_plan') >= before + 100


def test_the_book_readers_agree_with_legacy_on_this_checkout(departures):
    portfolio = json.loads((ROOT / 'portfolio.json').read_text())
    before = _calls('preposition.measurements')
    measured = preposition.measurements(ROOT, portfolio)
    assert set(measured) and _calls('preposition.measurements') == before + 1
    policy = preposition.load_policy()
    for ticker, row in measured.items():
        for information in (None, {}, {'state': 'active', 'direction': 'positive'}):
            for thesis in ('unknown', 'intact', 'damaged'):
                try:
                    preposition.setup(row, information, policy, ticker=ticker, leg='US',
                                      usage={}, cost_basis=10.0, thesis_state=thesis,
                                      hard_stop_pct=-18.0)
                except Exception:
                    pass  # The shadow holds legacy to the same error.
    for market in ('hk', 'us'):
        intraday_policy.load(ROOT, market)
    intraday_policy.reduce_exempt_strategies(ROOT)
    assert departures() == []
