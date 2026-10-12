"""The `strategy_scores` service: what each lab strategy says about the book today.

A strategy plugin is ranked by the lab and, until this row, read by nothing
else. This is the production reader. For every strategy the research rows
mount, it scores each stored series on its latest bar **under the parameters
the row registers**, ranks the cross-section, and attaches the lab's standing
for that strategy: the latest verdict, whether it survives without the names
one provider vouches for, each registration's score since, and any row edit
the lab has proposed.

What it does not do is the point of the arrangement. It never scores under a
searched or registered-but-unadopted parameter set, so a candidate changes
nothing here until someone edits the row. And it returns a reading, not a
permission: the block says `live_permission: false`, and no add, cut or size
is derived from it.

The research rows are mounted on first use, not when this row is: a research
plugin that fails to import must not take a live row down with it. If they
cannot be mounted, `read()` answers `status: unavailable` and says why.
"""
from __future__ import annotations

import json
from pathlib import Path

from clawock.strategy_lab import lab, ledger

name = 'strategy-scores'

SIGNAL_SOURCE = {
    'id': 'strategy-scores',
    'family': 'strategy',
    'summary': 'Each lab strategy\'s score and rank per stored name on its latest bar, under '
               'the registered parameters, with the lab\'s standing for that strategy.',
    'inputs': [
        {'name': 'bars', 'what': 'daily closes per name, oldest first, retired names left out',
         'source': 'memory/bars, raw, the store the brief settles on'},
        {'name': 'research rows', 'what': 'the mounted strategies and their registered parameters',
         'source': 'the plugins list of config/strategy-plugins.json'},
        {'name': 'lab record', 'what': 'latest verdict, registrations, proposed row edits',
         'source': 'memory/strategy-lab, written by the scheduled lab run'},
    ],
    'outputs': [
        {'field': 'strategies.<name>.rows.<ticker>.score', 'unit': 'the strategy\'s own score; higher is more bullish',
         'window': 'the strategy\'s registered parameters, on the name\'s latest bar',
         'missing': 'null when the strategy cannot score the name; it is then not ranked'},
        {'field': 'strategies.<name>.rows.<ticker>.rank', 'unit': 'position, 1 is the most bullish',
         'window': 'the names scored on this read', 'missing': 'null without a score'},
        {'field': 'strategies.<name>.ranked', 'unit': 'count of names scored',
         'window': 'this read', 'missing': 'zero when none could be scored'},
        {'field': 'strategies.<name>.standing', 'unit': 'the lab\'s latest record for the strategy',
         'window': 'the latest scheduled run',
         'missing': 'status is "no lab record" until the lab has recorded the strategy'},
    ],
    'missing': {
        'policy': 'omitted',
        'detail': 'When the research rows cannot be mounted or the bar store cannot be read, the '
                  'reading is empty and status is unavailable with the reason. A name whose '
                  'latest bar is older than the newest bar in the store is scored on its own '
                  'latest bar and carries that date.',
        'serves_stale': False,
    },
}


def _series(workspace: Path) -> dict[str, list[dict]]:
    out = {}
    for path in sorted((Path(workspace) / 'memory' / 'bars').glob('*.json')):
        document = json.loads(path.read_text(encoding='utf-8'))
        if document.get('retired'):
            continue
        store = document.get('bars') or {}
        rows = [{'date': day, 'close': store[day]['close']} for day in sorted(store)
                if store[day].get('close') is not None]
        if rows:
            out[path.stem] = rows
    return out


def standing(strategy: str) -> dict:
    """The lab's latest record for one strategy, in the terms a reader needs."""
    rows = [row for row in ledger.load() if row['strategy'] == strategy]
    if not rows:
        return {'status': 'no lab record'}
    latest = rows[-1]
    narrow = latest.get('coverage_sensitivity')
    trials = {(json.dumps(trial['params'], sort_keys=True), trial['after_session']): trial
              for trial in latest.get('prospective') or []}
    return {
        'status': latest['status'],
        'recorded_at': latest['recorded_at'],
        'refused_because': latest['refused_because'],
        'selected_params': latest['selected_params'],
        'cleared_for_registration': bool((latest.get('live_review') or {}).get('cleared')),
        'survives_adjusted_only': None if not narrow else narrow.get('verdict_survives'),
        'registrations': [
            {'params': record['params'], 'after_session': record['after_session'],
             'scored_since': trials.get(
                 (json.dumps(record['params'], sort_keys=True), record['after_session']))}
            for record in ledger.registrations() if record['strategy'] == strategy],
        'row_edits_proposed': [
            {'to_params': edit['to_params'], 'proposed_at': edit['proposed_at']}
            for edit in ledger.row_edits() if edit['strategy'] == strategy],
    }


class StrategyScores:
    def __init__(self, config: Path | None = None):
        self._config = config

    def read(self, workspace, tickers=None) -> dict:
        """Scores under registered parameters. `tickers` limits the rows reported;
        the rank is always over every stored name."""
        workspace = Path(workspace)
        try:
            kernel = lab.mount(lab.load_rows(self._config or workspace / lab.CONFIG))
        except Exception as exc:
            return {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}',
                    'live_permission': False, 'strategies': {}}
        try:
            series = _series(workspace)
            registry = kernel.get('strategies')
            strategies = {}
            for strategy in registry.names():
                spec = registry.get(strategy)
                scores = {}
                for ticker, rows in series.items():
                    score = spec.score(rows, spec.params)
                    scores[ticker] = None if score is None else round(score, 4)
                order = sorted((ticker for ticker, score in scores.items() if score is not None),
                               key=lambda ticker: (-scores[ticker], ticker))
                rank = {ticker: place for place, ticker in enumerate(order, 1)}
                wanted = sorted(series) if tickers is None else [t for t in tickers if t in series]
                strategies[strategy] = {
                    'params': dict(sorted(spec.params.items())),
                    'basis': 'the parameters the row registers; a candidate changes nothing here',
                    'ranked': len(order),
                    'rows': {ticker: {'score': scores[ticker], 'rank': rank.get(ticker),
                                      'last_bar': series[ticker][-1]['date']}
                             for ticker in wanted},
                    'standing': standing(strategy),
                }
            return {'status': 'ok', 'live_permission': False,
                    'as_of': max((rows[-1]['date'] for rows in series.values()), default=None),
                    'bars': 'memory/bars, raw', 'strategies': strategies}
        except Exception as exc:
            return {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}',
                    'live_permission': False, 'strategies': {}}
        finally:
            kernel.dispose()

    def describe(self) -> dict:
        return {'reads': 'registered parameters only'}


def apply(ctx, config):
    path = config.get('rows')
    ctx.provide('strategy_scores', StrategyScores(Path(path) if path else None))
