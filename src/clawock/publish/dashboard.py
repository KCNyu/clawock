#!/usr/bin/env python3
"""
Build the portable dashboard projection from a configured clawock workspace.

Outputs: assets/data/overview.json, assets/data/dashboard.json,
         assets/data/decision_audit.json, assets/data/shadow_portfolio.json

Run ``clawock dashboard-build`` after each portfolio mutation.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

from clawock.workspace import workspace_root
from clawock import history_store
from clawock import instruments as instrument_registry
from clawock import json_repair
from clawock.decision import ledger as decision_v2
from clawock.publish import outputs as dashboard_outputs
from clawock.publish import outcomes as dashboard_outcomes

# Strict YYYY-MM-DD.json — rejects baselines/backups/archives that share the
# snapshots dir (e.g. 2026-05-16-saturday-baseline.json caused duplicate 5-16
# rows in the equity curve before this filter was added). Aliased to the
# history_store constant so the #1040 roller and this reader cannot drift
# apart: what the roller archives must stay exactly what the equity curve
# already ignores.
SNAPSHOT_FNAME_RE = history_store.DATED_FILE_RE
# A session key inside a canonical bar document (memory/bars/<ticker>.json).
SESSION_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

WS_ROOT = workspace_root()
OUT_DIR = WS_ROOT / 'assets' / 'data'
OUT_FILE = OUT_DIR / 'dashboard.json'
OVERVIEW_FILE = OUT_DIR / 'overview.json'
AUDIT_FILE = OUT_DIR / 'decision_audit.json'

# ── Leg shape ────────────────────────────────────────────────────────────
# The ledger declares its own legs: `portfolio.json`'s `portfolios` is a mapping
# of bucket name to a book that carries its own `currency`. Deriving them from
# there is what lets the projection run against a workspace whose legs are not
# `us_stocks`/`hk_stocks` (#262 slice 3). It also avoids inventing a second
# source of truth — `config/instruments.json` describes instruments, not books.
LEG_BUCKET_SUFFIX = '_stocks'


class Leg(NamedTuple):
    bucket: str    # key inside portfolio['portfolios']
    key: str       # key inside the published payload
    currency: str  # the book's native currency


def resolve_legs(portfolio):
    """The legs this projection publishes, in the ledger's declaration order.

    The published key drops the `_stocks` suffix, which is the rule the payload
    has always followed (`us_stocks` → `out['us']`).

    Order is the ledger's and must stay that way: the payload is serialized
    without sorting keys, so reordering would rewrite every card without a
    reader seeing anything change — a commit `semantic_value()` cannot strip.
    """
    legs = []
    for bucket, book in (portfolio.get('portfolios') or {}).items():
        if not isinstance(book, dict):
            continue
        key = (bucket[:-len(LEG_BUCKET_SUFFIX)]
               if bucket.endswith(LEG_BUCKET_SUFFIX) else bucket)
        legs.append(Leg(bucket, key, book.get('currency') or ''))
    return legs


def leg_pair(portfolio):
    """The two legs a cross-leg aggregate needs, or `(None, None)`.

    Every combined figure in this file is "base leg + other leg converted at one
    rate", which is only defined for exactly two books. A workspace with one leg
    has nothing to combine; one with three would need an FX table this project
    does not have, and silently folding two of them would be a money bug. Both
    cases return `(None, None)` so the caller publishes its explicit `None`
    rather than a number nobody can reproduce.

    A book that does not declare its `currency` is refused for the same reason.
    The iron rule here is that HKD and USD may never be added; a combined figure
    whose base currency is unknown cannot be labelled, let alone checked.
    """
    legs = resolve_legs(portfolio)
    if len(legs) != 2 or not all(leg.currency for leg in legs):
        return (None, None)
    return (legs[0], legs[1])


def leg_books(portfolio):
    """The two books themselves, in ledger order, or `({}, {})`.

    Convenience for the many cards that want the books and not the metadata; the
    empty pair keeps their existing "degrade into the payload" behaviour when the
    ledger does not have the two-book shape a combined figure needs.
    """
    base, quote = leg_pair(portfolio)
    if not base:
        return {}, {}
    books = portfolio.get('portfolios') or {}
    return books.get(base.bucket) or {}, books.get(quote.bucket) or {}


def leg_totals(leg, book):
    """One leg's headline numbers, with its own currency in the field names.

    The suffix is the leg's currency, not the string 'usd' — the same reason the
    combined figures carry theirs. `cash_{ccy}` is also how the ledger itself
    names the field, so it is read the same way rather than by a second rule.
    """
    ccy = leg.currency.lower()
    return {
        f'value_{ccy}': book.get('total_current_value', 0),
        f'cost_{ccy}': book.get('total_cost', 0),
        f'pnl_{ccy}': book.get('total_pnl', 0),
        'pnl_pct': book.get('total_pnl_percent', 0),
        f'today_change_{ccy}': book.get('today_total_change', 0),
        f'realized_{ccy}': book.get('realized_pnl', 0),
        # 现金余额(kcn 对账手填) → 真实总资产 = 持仓市值 + 现金 (trade-invariant).
        # None = 该腿现金未跟踪（HK 长期如此）。
        f'cash_{ccy}': book.get(f'cash_{ccy}'),
    }


# ── Anti-bloat caps ──────────────────────────────────────────────────────
# Dashboard only embeds the most recent snapshots + plan summaries.
# Older history lives on disk; if dashboard ever needs full history, load lazily.
MAX_SNAPSHOTS_EMBEDDED = 90        # ≈ 4 months of trading days (kept in dashboard.json)
MAX_PLANS_EMBEDDED     = 5         # last 5 plans (each can be a few KB)
MAX_PLAN_BYTES         = 4096      # cap each plan blob to 4KB; if larger, just keep summary
MAX_OUT_BYTES          = 200_000   # final dashboard.json hard cap (~200KB)
#: Never trim the embedded snapshot series below this. `decision_metrics` reads
#: `snapshots[-30:]`, so a shorter series silently changes what that window
#: means rather than merely shortening a chart.
MIN_SNAPSHOTS_UNDER_BUDGET = 30
MAX_OVERVIEW_BYTES      = 80_000    # Hero-only projection hard cap


def _fields(value, names):
    """Copy an explicit public projection surface from an optional mapping."""
    value = value if isinstance(value, dict) else {}
    return {name: value.get(name) for name in names}


def compile_overview_projection(dashboard):
    """Compile the versioned Hero consumer from the canonical dashboard build.

    No money, health, or chart value is recomputed here: this is a deterministic
    field projection over the same in-memory object written to dashboard.json.
    Detail-only blocks therefore cannot drift into the first-paint contract.
    """
    generation = dashboard.get('generated_at')
    metrics = dashboard.get('decision_metrics') or {}
    delta = dashboard.get('decision_delta') or {}
    workflow = dashboard.get('workflow_outcomes') or {}
    guardrail = dashboard.get('risk_guardrail') or {}
    lev_regime = dashboard.get('lev_regime') or {}
    recent_plans = sorted(
        dashboard.get('recent_plans') or [],
        key=lambda row: str(row.get('date', '')),
        reverse=True,
    )[:1]

    active = _fields(metrics.get('active'), (
        'avg_benefit_pct', 'cluster_ci95', 'n_episodes',
        'capital_weighted_benefit_pct',
    ))
    by_driver = {
        name: _fields((metrics.get('by_driver') or {}).get(name),
                      ('win_rate', 'cluster_ci95'))
        for name in ('catalyst', 'technical', 'macro', 'peer')
    }
    # `stranded` travels with `rate`: it is how many rows the denominator drops
    # and never gets back (#294). Shipping the rate without it is what the
    # detail card was already fixed for; the Hero is the copy people see first.
    execution = _fields(
        (metrics.get('execution_by_kind') or {}).get('active'),
        ('rate', 'known', 'stranded'))
    active_calibration = _fields(
        (metrics.get('calibration') or {}).get('active'), ('baseline_loo', 'n'))
    compact_recent = [
        {
            **_fields(row, ('job', 'slot')),
            'raw_execution': _fields(row.get('raw_execution'), ('status',)),
            'final_product': _fields(row.get('final_product'), ('status',)),
            'readability': _fields(row.get('readability'), ('status', 'bytes')),
            # Channel truth per slot. The summary count answers "how many did
            # WeChat drop"; only the per-row flags can answer "which ones", and
            # the card is the only consumer that can show either (#771 made the
            # count exist in the summarizer — it never reached a reader).
            'primary_delivery': _fields(
                (row.get('stages') or {}).get('primary_delivery'),
                ('wechat_ok', 'telegram_ok')),
        }
        for row in workflow.get('recent') or [] if isinstance(row, dict)
    ]
    # Per-leg snapshot fields, grouped by metric the way the Hero projection has
    # always emitted them (both legs' `_asof`, then both `_total_value`, …).
    leg_keys = [leg.key for leg in _ledger_legs()]
    overview_equity_fields = ('date',) + tuple(
        f'{key}_{metric}'
        for metric in ('asof', 'total_value', 'cash', 'equity', 'total_cost', 'profit')
        for key in leg_keys
    )
    watch_holdings = []
    for region in leg_keys:
        for holding in (dashboard.get('holdings') or {}).get(region, []):
            if (holding.get('is_active', True) is False
                    or (holding.get('shares') or 0) <= 0):
                continue
            watch_holdings.append({
                **_fields(holding, ('ticker', 'current_price')),
                'region': region,
            })

    return {
        'schema_version': 1,
        'projection': 'overview',
        'generation_id': generation,
        **_fields(dashboard, (
            'generated_at', 'last_updated', 'fx', 'totals', 'indices', 'regime',
            'today_movers', 'anomalies', 'catalysts', 'debate_metrics',
            'build_status', 'delta', 'gold_dca', 'status_banner',
            'status_banner_meta', 'benchmark',
        )),
        'watch_holdings': watch_holdings,
        'recent_plans': [
            {
                'date': row.get('date'),
                'plan': {'watch_levels': (row.get('plan') or {}).get('watch_levels')},
            }
            for row in recent_plans if isinstance(row, dict)
        ],
        'decision_delta_summary': {
            'new_count': len(delta.get('new') or []),
            'changed_count': len(delta.get('changed') or []),
            'triggered_count': len(delta.get('triggered') or []),
            'active_overrides_count': len(delta.get('active_overrides') or []),
            'has_material_change': bool(delta.get('has_material_change')),
        },
        'decision_metrics': {
            **_fields(metrics, (
                'raw_decisions', 'brier', 'brier_beats_baseline',
                'brier_baseline_loo',
            )),
            'active': active,
            'by_driver': by_driver,
            'execution_by_kind': {'active': execution},
            'calibration': {'active': active_calibration},
        },
        'workflow_outcomes': {
            **_fields(workflow, (
                'counts', 'raw_error_but_product_usable',
                # Computed since #772 and, until now, dropped here: the card
                # could not answer "how many did WeChat drop this window" even
                # though the ledger knew. A count with no consumer is not a fix.
                'wechat_dropped_telegram_covered',
                # …and "which ones". Both lists are window-wide and capped;
                # `recent` cannot answer this because it is a tail, not a set.
                'wechat_dropped_slots', 'degraded_slots',
            )),
            'recent': compact_recent,
        },
        'risk_guardrail': {
            **_fields(guardrail, (
                'computed', 'error', 'breach_count', 'directive',
            )),
            'breaches': [
                _fields(row, ('type', 'severity', 'detail'))
                for row in guardrail.get('breaches') or [] if isinstance(row, dict)
            ],
            'hard_stop_watch': [
                _fields(row, ('severity', 'detail'))
                for row in guardrail.get('hard_stop_watch') or [] if isinstance(row, dict)
            ],
        },
        'overview_equity': [
            _fields(row, overview_equity_fields)
            for row in dashboard.get('snapshots') or [] if isinstance(row, dict)
        ],
        'lev_regime': _fields(lev_regime, ('ma', 'close', 'hk')),
    }


def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'  warn: failed to load {path}: {e}', file=sys.stderr)
        return None


def trim_decision_metrics(metrics):
    """Drop calibrator internals from the public payload, keep every headline.

    `hierarchical_calibration.current_group_calibrators` is 42 rows of posterior
    state — 27KB, larger than any chart on the page, and read by nothing: no
    renderer, no chart module, no test. The summary fields above it (method,
    hierarchy, abstain/sizing rules, counts) are what the calibration card shows.
    The detail stays reproducible from memory/decisions.jsonl.
    """
    if not isinstance(metrics, dict):
        return metrics
    hierarchical = metrics.get('hierarchical_calibration')
    if isinstance(hierarchical, dict) and 'current_group_calibrators' in hierarchical:
        groups = hierarchical['current_group_calibrators']
        hierarchical = {k: v for k, v in hierarchical.items()
                        if k != 'current_group_calibrators'}
        hierarchical['current_group_calibrator_count'] = (
            len(groups) if isinstance(groups, list) else None)
        metrics = {**metrics, 'hierarchical_calibration': hierarchical}
    return metrics


def trim_deep_risk(risk):
    """Keep the sentences, drop the working, for the copy embedded in the payload.

    `correlation.deep_risk` is about 4KB of per-name risk contributions, an HRP
    reference allocation and three stress scenarios — the same shape as the
    calibrator and regime-history trims above, and here for the same reason: the
    card reads a handful of headline numbers and the detail is already published
    in full at `assets/data/risk.json`, one fetch away. The payload has roughly
    20KB of headroom under the 200KB cap and this block would take a fifth of it
    to be rendered by nothing.

    What survives is what a reader would act on: how badly conditioned the
    estimate is, how hard it had to be shrunk, the single largest risk
    overweight, and the two numbers from the shock.
    """
    if not isinstance(risk, dict):
        return risk
    correlation = risk.get('correlation')
    if not isinstance(correlation, dict):
        return risk
    deep = correlation.get('deep_risk')
    if not isinstance(deep, dict) or deep.get('status') != 'measured':
        return risk
    shock = ((deep.get('stress') or {}).get('correlated_shock') or {})
    reverse = ((deep.get('stress') or {}).get('reverse_stress') or {})
    summary = {
        'status': 'measured',
        'conditioning': deep.get('conditioning'),
        'shrinkage': deep.get('shrinkage'),
        'largest_risk_overweight': deep.get('largest_risk_overweight'),
        'top_position_shock': {
            'name': (deep.get('stress') or {}).get('top_position'),
            'move': (shock.get('shocked') or {}).get(
                (deep.get('stress') or {}).get('top_position')),
            'portfolio_return': shock.get('portfolio_return'),
            'portfolio_return_if_others_held_still':
                shock.get('portfolio_return_if_others_held_still'),
            'contagion_share': shock.get('contagion_share'),
        },
        'sigmas_to_lose': {
            key: value.get('sigmas_away')
            for key, value in reverse.items() if isinstance(value, dict)
        },
        'detail_source': 'assets/data/risk.json',
    }
    return {**risk,
            'correlation': {**correlation, 'deep_risk': summary}}


def trim_lev_regime(lev_regime):
    """The dial as the card needs it: everything except the unrendered history."""
    if not isinstance(lev_regime, dict):
        return lev_regime
    trimmed = {k: v for k, v in lev_regime.items() if k != 'regime_history'}
    if 'regime_history' in lev_regime:
        trimmed['regime_history_source'] = 'assets/data/lev_regime.json'
    return trimmed


def trim_workflow_outcomes(summary):
    """Keep build-status fields and compact readability; drop stage detail.

    `recent[].stages` is five stage objects per slot, each carrying the full
    heartbeat detail (market, anomaly_count, wechat_sent, …) — 24KB across a
    36h window, and the renderer touches none of it: the dot reads `counts`
    and `raw_error_but_product_usable`, the tooltip reads only `job`, `slot`,
    `raw_execution.status`, `final_product.status`, and the compact readability
    assessment. The complete ledger is published on its own at
    assets/data/workflow-outcomes.json, so this is the same duplication the
    calibrator and regime-history trims removed.
    """
    if not isinstance(summary, dict):
        return summary
    recent = summary.get('recent')
    if not isinstance(recent, list):
        return summary
    trimmed = []
    dropped = False
    for record in recent:
        if not isinstance(record, dict):
            trimmed.append(record)
            continue
        stages = record.get('stages')
        compact = {k: v for k, v in record.items() if k != 'stages'}
        if isinstance(stages, dict):
            # 通道位随行留下：数据健康卡的逐项要答「微信掉的是哪几档」，
            # 而全量 payload 在首帧之后会把 DATA 整个换掉 —— 只在 overview
            # 投影里留，卡片一秒后就失忆。两个布尔，不是把 stages 加回来。
            delivery = stages.get('primary_delivery')
            if isinstance(delivery, dict):
                compact['primary_delivery'] = {
                    key: delivery.get(key) for key in ('wechat_ok', 'telegram_ok')
                }
            # llm is written immediately before the dashboard build, so it is
            # current even on a same-slot retry whose older postflight detail is
            # still present. Both stages carry the same assessment on first run.
            for stage_name in ('llm', 'postflight'):
                stage = stages.get(stage_name)
                candidate = stage.get('readability') if isinstance(stage, dict) else None
                if isinstance(candidate, dict):
                    compact['readability'] = candidate
                    break
        dropped = dropped or 'stages' in record
        trimmed.append(compact)
    summary = {**summary, 'recent': trimmed}
    if dropped:
        summary['stages_source'] = 'assets/data/workflow-outcomes.json'
    return summary


#: How many debated decisions ride the Reflect sidecar. The block is ~1.1KB of
#: UTF-8 per decision, so a window rather than the whole ledger; the counts in
#: `debate_metrics` stay whole-ledger, so a shrinking window cannot hide a
#: falling coverage series.
DEBATE_SIDECAR_LIMIT = 30


def build_debate_sidecar(decisions, limit=DEBATE_SIDECAR_LIMIT):
    """The debate behind each decision, published rather than asserted (#1117).

    README claims Bull/Bear/Judge with a named devil's advocate. Until now the
    only public trace of it was a count: `debate_metrics.debate_coverage` said
    how many decisions carried a debate block, never what was argued. A reader
    outside this repository could verify that we *recorded* a debate and not
    that one happened — which is the exact move clawock attacks competitors for.

    So the structured block goes out with the decision it produced: the bull
    case, the bear case, the consensus that was attacked by name, the Judge's
    verdict and the strategy frames it was decided under. Text is already
    capped at `ledger.DEBATE_TEXT_CHARS` upstream, so a runaway field cannot
    walk this sidecar into the payload budget.

    Rows are newest-first and carry the decision id, so a reader can join them
    against `recent_decisions` / the ledger and check that the debate published
    here belongs to the call that was actually made.
    """
    rows = []
    ordered = sorted(
        decisions or [],
        key=lambda x: (x.get('created_at', ''), x.get('decision_id', '')),
        reverse=True,
    )
    for d in ordered:
        debate = d.get('debate')
        if not isinstance(debate, dict) or not debate:
            continue
        row = {
            'date': d.get('plan_date'),
            'decision_id': d.get('decision_id'),
            'ticker': d.get('ticker'),
            'name': d.get('name'),
            'action': d.get('action'),
            'confidence': d.get('confidence'),
        }
        for field in decision_v2.DEBATE_TEXT_FIELDS:
            value = debate.get(field)
            if isinstance(value, str) and value.strip():
                row[field] = value.strip()
        frames = debate.get('frames')
        if isinstance(frames, list) and frames:
            row['frames'] = [str(f) for f in frames]
        cited = debate.get('evidence_ids')
        if isinstance(cited, list) and cited:
            row['evidence_ids'] = [str(ref) for ref in cited]
        rows.append(row)
        if len(rows) >= limit:
            break
    return {'limit': limit, 'rows': rows}


def build_decision_audit_payload(decisions, portfolio):
    """Compile the complete Reflect sidecar from one settled decision set.

    ``episode_backtest`` is rendered only on Reflect, whose existing
    ``decision_audit.json`` dependency is already fetched before that tab
    paints. Keeping it here avoids taxing every other tab while preserving one
    logical dashboard build and the existing four-output publication contract.
    """
    payload = decision_v2.build_audit_sidecar(
        decisions, portfolio, include_records=False
    )
    payload['episode_backtest'] = decision_v2.compute_backtest(decisions)
    # The debate itself, not just how often one was recorded (#1117). It rides
    # this sidecar rather than dashboard.json because Reflect is the only tab
    # that renders it and dashboard.json is the payload under the 200KB cap.
    payload['debates'] = build_debate_sidecar(decisions)
    return payload


def serialize_dashboard_payload(value):
    """Serialize a browser projection without spending headroom on whitespace."""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


SNAPSHOTS_PACKED_COLUMNS_KEY = 'snapshots_columns'


def pack_snapshots(rows):
    """Row dicts -> (column names, row value lists). Identity, not a summary.

    The equity series was 18% of `dashboard.json` and 58% of that was the same
    eighteen field names repeated on every row: `us_total_value`,
    `hk_today_change`, `us_realized` and the rest, 262 bytes of key against 187
    bytes of value (measured 2026-08-31, 79 rows, 449 bytes each). It is the
    only section that grows by a row every trading day, so it is what walks the
    payload into the cap — and the cap's only answer was to delete the oldest
    rows, i.e. to pay for the field names with 46 days of curve.

    Naming the columns once turns ~35.5KB into ~15KB and buys roughly forty
    trading days of headroom without dropping a single point. `snapshots` stays
    a non-empty list so the published-shape assertions still hold; the browser
    rebuilds the dicts on load, so no consumer sees the wire form.

    A row missing a column gets None rather than a shortened list: a ragged row
    would silently shift every later value into the wrong field.
    """
    rows = [row for row in rows or [] if isinstance(row, dict)]
    if not rows:
        return [], []
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns, [[row.get(name) for name in columns] for row in rows]


def unpack_snapshots(columns, rows):
    """The inverse. Used by the readers that consume a published payload."""
    columns = list(columns or [])
    if not columns:
        return [row for row in rows or [] if isinstance(row, dict)]
    return [dict(zip(columns, row)) for row in rows or [] if isinstance(row, list)]


def snapshots_of(payload):
    """Row dicts out of a published dashboard payload, packed or not.

    Every reader of a *published* `snapshots` goes through here, so the two
    encodings cannot drift into two code paths — the mistake that this file
    already made once with the fingerprint tuple.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get('snapshots') or []
    return unpack_snapshots(payload.get(SNAPSHOTS_PACKED_COLUMNS_KEY), rows)


def dashboard_wire_payload(out):
    """Serialize the dashboard document with the equity series column-packed.

    `out` is not mutated: `compile_overview_projection` reads `out['snapshots']`
    as row dicts, and the size levers measure the *wire* bytes, so the two have
    to see different shapes of the same data at the same moment.
    """
    columns, rows = pack_snapshots(out.get('snapshots'))
    if not columns:
        return serialize_dashboard_payload(out)
    return serialize_dashboard_payload(
        {**out, SNAPSHOTS_PACKED_COLUMNS_KEY: columns, 'snapshots': rows})


def _guardrail_sections(portfolio, risk, lev_regime=None):
    from clawock.portfolio.guardrail import (
        compute_breakeven_math,
        compute_concentration,
        compute_risk_guardrail,
    )

    us_book = portfolio['portfolios']['us_stocks']
    hk_book = portfolio['portfolios']['hk_stocks']
    hk_holdings = hk_book['holdings']
    us_holdings = us_book['holdings']
    guardrail = compute_risk_guardrail(
        hk_holdings, us_holdings,
        compute_concentration(hk_holdings), compute_concentration(us_holdings),
        risk or {}, lev_regime=lev_regime,
    )
    breakeven = compute_breakeven_math(
        hk_holdings, us_holdings, lev_regime=lev_regime)
    if isinstance(guardrail, dict) and isinstance(guardrail.get('lev_regime'), dict):
        guardrail['lev_regime_tier'] = guardrail['lev_regime'].get('tier')
        guardrail.pop('lev_regime')
    return {'risk_guardrail': guardrail, 'breakeven_math': breakeven}


GUARDRAIL_HISTORY_NAME = 'guardrail_history.jsonl'
GUARDRAIL_HISTORY_DAYS = 30


def load_guardrail_history(ws=None, limit=None):
    """Every recorded guardrail verdict, oldest first (or the last `limit`).

    Read whole by default: a breach's age must be measured against the whole
    record, while only the tail is worth the payload budget. Coupling the two
    would make every age read "30 天+" the moment the chart window filled.

    `brief_preflight._append_guardrail_history` writes one row per brief and is
    idempotent by date, so a row is a trading day rather than a calendar day —
    weekends and holidays are absent, not zero. Callers must count rows, never
    subtract dates.

    Never raises: the risk card must still render when this file is missing (a
    fresh clone has none) or when a line is torn mid-append.
    """
    path = Path(ws or WS_ROOT) / 'assets' / 'data' / GUARDRAIL_HISTORY_NAME
    rows = []
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get('date'), str):
            rows.append(row)
    rows.sort(key=lambda r: r['date'])
    return rows[-limit:] if limit else rows


def _breach_identity(row):
    """What makes two breaches, recorded on different days, the same breach."""
    if not isinstance(row, dict):
        return None
    return (row.get('type') or 'hard_stop', row.get('leg'), row.get('ticker'))


def _consecutive_age(identity, history, key):
    """How many of the newest consecutive recorded days carry `identity`.

    Returns (days, capped). `capped` says the streak reaches the oldest row on
    record, so the true age is at least this — the file starts 2026-07-15 and
    nothing before it can be reconstructed. Rendering ">= 34" as "34" would be
    the card asserting a number it does not have.
    """
    days = 0
    for row in reversed(history):
        present = any(_breach_identity(r) == identity for r in (row.get(key) or []))
        if not present:
            break
        days += 1
    return days, bool(days) and days == len(history)


def annotate_guardrail_history(guardrail, history):
    """Give the risk card the two questions it could not answer (#1252).

    Until now it rendered only the current `breaches` / `hard_stop_watch`, so it
    answered "what is tripped right now" and nothing else. The data for the other
    two was already being published — `guardrail_history.jsonl` has carried a
    full daily row since 2026-07-15 — it just never reached the browser:

      * trend — is the gate tightening or loosening? (34 recorded days run
        12 -> 6, which the card could not show)
      * age — how long has THIS breach been tripped?

    An age of 0 is meaningful and kept: the breach is live now but was not in
    the newest recorded row, i.e. it appeared after this morning's brief.
    Mutates `guardrail` in place and returns it. Never raises.
    """
    if not isinstance(guardrail, dict) or guardrail.get('computed') is False:
        return guardrail
    try:
        guardrail['breach_history'] = [
            {'date': row['date'], 'count': row.get('breach_count')}
            for row in history if isinstance(row.get('breach_count'), int)
        ][-GUARDRAIL_HISTORY_DAYS:]
        for key in ('breaches', 'hard_stop_watch'):
            for entry in (guardrail.get(key) or []):
                if not isinstance(entry, dict):
                    continue
                days, capped = _consecutive_age(
                    _breach_identity(entry), history, key)
                entry['age_days'] = days
                if capped:
                    entry['age_capped'] = True
    except Exception as e:  # a decoration must not be able to fail a publish
        print(f'  warn: guardrail history annotate failed: {e}', file=sys.stderr)
    return guardrail


def compute_guardrail_outputs(portfolio, risk, lev_regime=None):
    """Compute the two live risk cards without ever failing the dashboard build.

    The frontend must be able to distinguish "computed and no breaches" from
    "could not compute".  Returning ``None`` erased that distinction because the
    renderer normalized it to ``{}`` and painted a green all-clear.
    """
    try:
        return _guardrail_sections(portfolio, risk, lev_regime)
    except Exception as e:
        print(f'  warn: risk_guardrail compute fail: {e}', file=sys.stderr)
        return {
            'risk_guardrail': {'error': str(e), 'computed': False},
            'breakeven_math': {'computed': False},
        }


def build_shadow_sidecar(portfolio, decisions, previous=None):
    """Build the shadow sidecar payload, replacing a stale result with a failure.

    A failed refresh must never leave the previous curves looking current.  Keep
    the last successful ``as_of`` only as provenance on the failure marker; a
    later successful full build naturally removes ``computed: false`` again.

    ``previous`` is the sidecar as it currently stands on disk. It is passed in
    rather than read here because this no longer knows where the sidecar lives —
    the caller owns that, and the failure marker is the only thing that needs the
    old value at all.
    """
    try:
        import importlib
        shadow_portfolio = importlib.import_module('clawock.decision.shadow')
        leg_config = shadow_portfolio.load_leg_config(
            WS_ROOT / 'config' / 'portfolio-derivations.json')
        return shadow_portfolio.build_shadow_portfolio(
            portfolio, decisions, leg_config=leg_config)
    except Exception as e:
        failure = {'computed': False, 'error': str(e)}
        if isinstance(previous, dict):
            stale_as_of = previous.get('as_of') or previous.get('stale_as_of')
            if stale_as_of:
                failure['stale_as_of'] = stale_as_of
        print(f'  warn: shadow_portfolio build fail: {e}', file=sys.stderr)
        return failure


def trim_holding(h, currency):
    """Trim a holding dict to UI-relevant fields."""
    return {
        'ticker': h.get('ticker') or h.get('code'),
        'name': h.get('name') or h.get('stock_name', ''),
        'currency': currency,
        'shares': h.get('shares', 0),
        'cost_basis': round(h.get('cost_basis') or 0, 4),
        'current_price': round(h.get('current_price') or 0, 4),
        'current_value': round(h.get('current_value') or 0, 2),
        'today_change': round(h.get('today_change') or 0, 2),
        'today_change_pct': round(h.get('today_change_pct') or 0, 2),
        'day_high': round(h.get('day_high') or 0, 4),
        'day_low': round(h.get('day_low') or 0, 4),
        'pnl_abs': round(h.get('pnl_abs') or 0, 2),
        'pnl_percent': round(h.get('pnl_percent') or 0, 2),
        'is_active': (h.get('shares') or 0) > 0,
        'trades_count': len(h.get('trades') or []),
    }


def compute_hhi(holdings):
    """HHI = Σ weight²; return (hhi, top2, weights[], total_value)."""
    active = [h for h in holdings if h['is_active'] and h['current_value'] > 0]
    total = sum(h['current_value'] for h in active)
    if total <= 0:
        return {'hhi': 0, 'top2': 0, 'positions': [], 'total': 0}
    weights = []
    for h in active:
        w = h['current_value'] / total
        weights.append({
            'ticker': h['ticker'],
            'name': h['name'],
            'value': h['current_value'],
            'weight': round(w, 4),
        })
    weights.sort(key=lambda x: -x['weight'])
    hhi = round(sum(w['weight'] ** 2 for w in weights), 4)
    top2 = round(sum(w['weight'] for w in weights[:2]), 4)
    return {'hhi': hhi, 'top2': top2, 'positions': weights, 'total': round(total, 2)}


def hhi_verdict(hhi, top2):
    if hhi < 0.15 and top2 < 0.40:
        return {'level': 'healthy', 'label': '健康', 'color': '#4ade80'}
    if hhi < 0.25 and top2 < 0.60:
        return {'level': 'moderate', 'label': '偏集中', 'color': '#facc15'}
    if hhi < 0.40 and top2 < 0.75:
        return {'level': 'concentrated', 'label': '集中风险', 'color': '#fb923c'}
    return {'level': 'danger', 'label': '危险集中', 'color': '#ef4444'}


def build_holdings_history(snapshot_paths, days=8):
    """Extract per-ticker current_price series from the last N snapshots.

    Returns { ticker: [price_or_null, ...] } in chronological order. Tickers
    that are missing from a given day get null, so the array length is constant
    and the frontend can simply slice it.

    Used by the holdings table for its trailing 7d sparkline and by the Drill
    panel for the explicitly labelled trailing 8-snapshot return heatmap.
    """
    paths = snapshot_paths[-days:]
    out = {}
    for p in paths:
        d = load_json(p)
        if not d:
            continue
        for leg in _ledger_legs():
            for h in (d.get('portfolios', {}).get(leg.bucket, {}).get('holdings') or []):
                t = h.get('ticker') or h.get('code')
                if not t:
                    continue
                out.setdefault(t, []).append(h.get('current_price'))
    # Right-align: if a ticker appeared late, pad the head with None so length matches paths
    n = len(paths)
    for t, arr in out.items():
        if len(arr) < n:
            arr[:0] = [None] * (n - len(arr))
        out[t] = arr[-n:]  # safety cap
    return out


def _aggregate_indices(us_pf, hk_pf):
    """Combine US + HK leg indices into one flat dict for the dashboard.

    portfolio.json stores them per-leg (legacy: only US leg was read), so HK
    indices (HSI/HSTECH) were invisible to the frontend even though they're
    fetched daily by analyze_hk_stocks.py. Normalize key shape to:

        { TICKER: {name, price, prev_close, change_pct, source} }

    where TICKER is NDX/SPX/HSI/HSTECH/etc.
    """
    out = {}
    for leg in (us_pf or {}, hk_pf or {}):
        idx = leg.get('indices_snapshot') or {}
        for k, v in idx.items():
            if not isinstance(v, dict):
                continue
            # Different sources use chg_pct vs change_pct — normalize
            normalized = {
                'name':       v.get('name', k),
                'price':      v.get('price'),
                'prev_close': v.get('prev_close'),
                'change_pct': v.get('change_pct') if v.get('change_pct') is not None else v.get('chg_pct'),
                'source':     v.get('source', 'unknown'),
            }
            out[k] = normalized
    return out


_MONTHS = {m: i for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
_ASOF_RE = re.compile(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})(?:,\s*(\d{4}))?')


def _session_asof(region_pf, fallback_year):
    """The market-session date (YYYY-MM-DD) a snapshot's prices belong to, parsed
    from an ACTIVE holding's data_source (exited names carry stale dates).

    Why: US trades during HK night, so one US session (e.g. Jun 8 ET) lands in BOTH
    the HK-6/8 and HK-6/9 snapshots. Keying daily P&L by this session date — not the
    HK filename date — stops the same session being counted twice (2026-06-08/09 bug).
    Formats seen: 'Nasdaq API (stocks) Jun 08, 2026 13:23 ET', 'Tencent Jun 08 16:00 HKT'."""
    for h in (region_pf.get('holdings', []) or []):
        if (h.get('shares', 0) or 0) <= 0:
            continue
        m = _ASOF_RE.search(h.get('data_source') or '')
        if m:
            mon, day, yr = _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3) or fallback_year)
            return f'{yr:04d}-{mon:02d}-{day:02d}'
    return None


_LEDGER_CACHE = None


_LEDGER_LEGS_CACHE = None


def _ledger_legs():
    """The live ledger's legs, cached for the process.

    Snapshots carry the same `portfolios.{bucket}` shape as portfolio.json, but
    an individual snapshot may predate a book. Reading the leg list from the
    CURRENT ledger rather than from each snapshot keeps one stable key set across
    every row — the frontend indexes `<leg>_equity` on all of them, so a row that
    silently dropped a leg would break the curve rather than shorten it.
    """
    global _LEDGER_LEGS_CACHE
    if _LEDGER_LEGS_CACHE is None:
        try:
            _LEDGER_LEGS_CACHE = resolve_legs(
                load_json(str(WS_ROOT / 'portfolio.json')) or {})
        except Exception:
            _LEDGER_LEGS_CACHE = []
    return _LEDGER_LEGS_CACHE


def _canonical_ledger():
    """portfolio.json holdings per leg — the realized-P&L source of truth.
    Cached for the lifetime of the process. Returns {} on any failure."""
    global _LEDGER_CACHE
    if _LEDGER_CACHE is None:
        try:
            d = load_json(str(WS_ROOT / 'portfolio.json')) or {}
            pf = d.get('portfolios', {})
            _LEDGER_CACHE = {
                leg.bucket: pf.get(leg.bucket, {}).get('holdings', []) or []
                for leg in resolve_legs(d)
            }
        except Exception:
            _LEDGER_CACHE = {}
    return _LEDGER_CACHE


def _day_num(iso):
    """Calendar day ordinal for window arithmetic; None for unparsable values.

    Must be a real day count, not a y*400+m*32+d packing: the packed form
    silently shortens every window that crosses a month (by 32 − days-in-month)
    and makes a year boundary unreachable — 2026-12-31 → 2027-01-01 packs to a
    distance of 18, so a January fill could never pair with a late-December
    plan. The DSH plugin's `dayGap` is calendar-correct; this is the same rule.
    """
    if not isinstance(iso, str):
        return None
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', iso)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).toordinal()
    except ValueError:
        return None


# How far after a fill a close may sit and still be called T+1. A Friday fill
# settles against Monday (3 calendar days); one intervening public holiday makes
# 4. Beyond that it is a different horizon and must not wear the T+1 label.
# Mirrors T1_MAX_GAP_DAYS in the DSH plugin (examples/dsh/.../src/ledger.ts).
T1_MAX_GAP_DAYS = 4
# Moves smaller than this read as noise, not as a verdict. Mirrors the plugin's
# T1_FLAT_BAND_PCT. Tone and verdict share it so the coloured chip and the words
# can never disagree about the same fill.
T1_FLAT_BAND_PCT = 1
# Actions that reduce a position — for these a rising close is bad news.
T1_SELL_ACTIONS = ('sell', 'cut', 'trim', 'trim_on_rebound')


def _t1_tone(action, delta):
    """'win' | 'loss' | 'flat' reading of a T+1 move, action-aware, dead-zoned."""
    if abs(delta) < T1_FLAT_BAND_PCT:
        return 'flat'
    up = delta > 0
    if action in T1_SELL_ACTIONS:
        return 'loss' if up else 'win'
    return 'win' if up else 'loss'


def _t1_verdict(action, delta):
    """Verdict text for a T+1 move, on the same dead zone as `_t1_tone`."""
    if abs(delta) < T1_FLAT_BAND_PCT:
        return '持平'
    up = delta > 0
    if action in T1_SELL_ACTIONS:
        return '卖飞' if up else '卖对'
    return '涨' if up else '跌'


def _future_close(prices_by_ticker, ticker, date_iso, n=1, max_gap_days=T1_MAX_GAP_DAYS):
    """The n-th canonical close strictly after date_iso, or None.

    The gap ceiling is load-bearing: the bar store has holes (holidays, a
    retired ticker, a fill that predates coverage), so "the next close we
    happen to own" can be months later. Without the ceiling those were being
    rendered under a literal T+1 label.
    """
    days = prices_by_ticker.get(ticker)
    if not days:
        return None
    base = _day_num(date_iso)
    if base is None:
        return None
    later = sorted(d for d in days if (_day_num(d) or 0) > base)
    if len(later) < n:
        return None
    hit = later[n - 1]
    if (_day_num(hit) - base) > max_gap_days:
        return None
    return hit, days[hit]


def _bar_close_index(workspace=None, tickers=None):
    """{ticker: {date: close}} from the canonical bar store memory/bars/*.json.

    Deliberately NOT memory/snapshots/*.json. A snapshot is a *portfolio* file
    whose `current_price` carries the vintage of whichever cron wrote it —
    measured on 00100 across 15 snapshots it was the previous close 7 times,
    that day's close 3 times and an intraday print 5 times — and the field is
    carried forward after a position closes. Settlement migrated off snapshots
    for exactly this reason; this view read them until #740, where 9 of the 40
    published T+1 verdicts turned out to be wrong (SPCH 2026-06-18 showed
    −10.64% against a real −40.33%). `bars.py` START_DATE was lowered to
    2025-12-01 specifically so this view could mark fills against real closes.
    """
    index = {}
    ws = workspace or WS_ROOT
    wanted = None if tickers is None else {t for t in tickers if isinstance(t, str)}
    for p in sorted(glob.glob(str(ws / 'memory' / 'bars' / '*.json'))):
        ticker = os.path.basename(p)[:-len('.json')]
        if wanted is not None and ticker not in wanted:
            continue
        d = load_json(p)
        if not isinstance(d, dict):
            continue
        # `bars` must be a mapping. A list here (a hand-edited or
        # half-migrated doc) would raise on .items() and take the whole
        # dashboard build down with it — the plugin's reader type-guards for
        # the same reason.
        raw_bars = d.get('bars')
        if not isinstance(raw_bars, dict):
            continue
        closes = {}
        for day, bar in raw_bars.items():
            if not isinstance(day, str) or not SESSION_DATE_RE.match(day):
                continue
            close = bar.get('close') if isinstance(bar, dict) else None
            if isinstance(close, (int, float)) and math.isfinite(close):
                closes[day] = close
        if closes:
            index[ticker] = closes
    return index


def build_decision_traces(limit=40, workspace=None):
    """The decision-trace view data: every real fill as a trace node with its
    soft-paired decision (±3 calendar days, same ticker) and T+1 close verdict.

    This is the organic "one view" the DSH plugin and this dashboard card both
    render: the spine is real fills (portfolio.json trades[]), the "why" layer
    is the decision ledger, the result is the T+1 canonical close.
    Pure read — never mutates portfolio.json or the ledger.
    @param workspace - desk root; defaults to the module WS_ROOT (used by the
                       real build). Tests pass a synthetic temp dir.
    @returns list of trace dicts, newest first, capped at `limit`. The card's
             own totals must come from `build_decision_trace_scope`, never from
             summing this window (#737).
    """
    ws = workspace or WS_ROOT
    # Prices first (needed for T+1 verdicts). Canonical bars, never snapshots.
    prices = _bar_close_index(ws)
    # Decision ledger by ticker+date (last row wins on same-key collisions).
    decisions = decision_v2.load_decisions(ws / 'memory' / 'decisions.jsonl')
    dec_by_key = {}
    for e in decisions:
        tk = e.get('ticker') or (e.get('subject') or {}).get('ticker')
        dt = e.get('plan_date') or (e.get('decided_at') or '')[:10]
        if isinstance(tk, str) and isinstance(dt, str) and dt:
            dec_by_key[tk + ':' + dt] = e
    # Portfolio doc (single read, used for holdings/trades/positions).
    pf_doc = load_json(str(ws / 'portfolio.json')) or {}
    # Current-position P&L lookup for still-held tickers.
    held_pnl = {}
    for book in (pf_doc.get('portfolios') or {}).values():
        if not isinstance(book, dict):
            continue
        for h in (book.get('holdings') or []):
            if not isinstance(h, dict):
                continue
            if (h.get('shares') or h.get('quantity') or 0) > 0 and h.get('pnl_percent') is not None:
                held_pnl[h.get('ticker')] = h.get('pnl_percent')
    # Flatten all trades with market/currency context.
    traces = []
    for leg in resolve_legs(pf_doc):
        for h in (pf_doc.get('portfolios') or {}).get(leg.bucket, {}).get('holdings', []):
            if not isinstance(h, dict):
                continue
            ticker = h.get('ticker')
            for tr in (h.get('trades') or []):
                if not isinstance(tr, dict) or not isinstance(tr.get('date'), str):
                    continue
                t = {
                    'ticker': ticker,
                    'market': leg.key,
                    'currency': leg.currency,
                    'date': tr.get('date'),
                    'action': tr.get('action') or 'buy',
                    'shares': tr.get('shares') or 0,
                    'price': tr.get('price'),
                    'realizedPnl': tr.get('realized_pnl'),
                    'note': tr.get('note') if isinstance(tr.get('note'), str) else None,
                    't1': None,
                    'decision': None,
                    'holdPnl': None,
                }
                # T+1 verdict. `tone` ships with the verdict so the rendered
                # chip cannot colour a move the words call 持平 (#739).
                fc = _future_close(prices, ticker, t['date'], 1)
                if fc and t.get('price'):
                    delta = round((fc[1] - t['price']) / t['price'] * 100, 2)
                    t['t1'] = {
                        'date': fc[0],
                        'price': round(fc[1], 2),
                        'delta': delta,
                        'verdict': _t1_verdict(t['action'], delta),
                        'tone': _t1_tone(t['action'], delta),
                    }
                # Soft-pair the decision ledger (±3 calendar days).
                base = _day_num(t['date'])
                best = None
                best_diff = 99
                prefix = (ticker or '') + ':'
                for key, e in dec_by_key.items():
                    if not key.startswith(prefix):
                        continue
                    plan_day = _day_num(key[len(prefix):])
                    if plan_day is None or base is None:
                        continue
                    diff = abs(plan_day - base)
                    if diff <= 3 and diff < best_diff:
                        best = e
                        best_diff = diff
                if best:
                    subject = best.get('subject') or {}
                    mind = best.get('mind') or {}
                    emotion = best.get('emotion') or {}
                    size = best.get('size') or {}
                    evaluation = best.get('evaluation') or {}
                    t['decision'] = {
                        'planDate': best.get('plan_date') or (best.get('decided_at') or '')[:10],
                        'action': best.get('action'),
                        'confidence': best.get('confidence'),
                        'drivenBy': best.get('driven_by'),
                        'rationale': _readable_rationale(best.get('rationale')),
                        'thesis': mind.get('thesis'),
                        'invalidation': mind.get('invalidation') if isinstance(mind.get('invalidation'), list) else [],
                        'bull': (mind.get('bull') or {}).get('summary'),
                        'bear': (mind.get('bear') or {}).get('summary'),
                        'emotion': emotion.get('pressure'),
                        'emotionNote': emotion.get('note'),
                        'execution': (best.get('execution') or {}).get('status'),
                        'condition': (best.get('condition') or {}).get('description'),
                        # Coerced, because the renderer interpolates these into
                        # HTML without escaping (they are numbers by contract).
                        # A hand-written ledger row carrying a string here would
                        # otherwise reach the page verbatim. The plugin's reader
                        # runs them through Number() for the same reason.
                        'sizeShares': _as_number(size.get('shares')),
                        'sizePct': _as_number(size.get('pct')),
                        'plannedPrice': _as_number(
                            evaluation.get('execution_price') or best.get('simulated_entry_price')),
                        'source': best.get('source') or 'brief',
                        # How the plan's direction relates to the fill that
                        # actually happened. The ledger's own execution.status
                        # is a plan self-report and answers a different
                        # question, so it must not be rendered as if it graded
                        # this fill (#738).
                        'alignment': _plan_fill_alignment(best.get('action'), t['action']),
                    }
                if ticker in held_pnl:
                    t['holdPnl'] = held_pnl[ticker]
                traces.append(t)
    traces.sort(key=lambda t: (t.get('date') or ''), reverse=True)
    return traces[:limit]


def _as_number(value):
    """`value` as a finite number, else None. Bools are not numbers here."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _readable_rationale(text, cap=140):
    """A rationale fit for a public card: internal breach ids stripped, then
    truncated to the payload budget.

    Raw rationales leak the risk engine's internals — "硬止损 -27.23% ≤ -18%
    (breach risk-95ac7f6cd591 30d)" — into the one field a reader looks at to
    understand *why*. The hash says nothing to anyone outside the process, and
    it was eating the 140-char budget the real sentence needed (#738).
    Truncation stays because the full text blew the 200KB dashboard cap.
    """
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r'\s*\((?:breach\s+)?risk-[0-9a-f]{6,}(?:\s+\d+d)?\)', '', text)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned).strip()
    if not cleaned:
        return None
    return (cleaned[:cap] + '…') if len(cleaned) > cap else cleaned


# Fill actions grouped by what they do to a position, so a plan can be compared
# with the fill that followed it.
_ADD_SIDE = ('buy', 'add')
_REDUCE_SIDE = ('sell', 'cut', 'trim', 'trim_on_rebound')


def _plan_fill_alignment(plan_action, fill_action):
    """'same' | 'opposite' | 'other' — the plan's direction vs the fill's.

    Not cosmetic: 39 of the 40 published traces had a plan action that differed
    from the fill, and the card said nothing about it. "Plan said cut, I bought"
    is the single most informative thing on this panel, so it ships as data
    instead of being left for the reader to infer from two adjacent lines.
    """
    if not isinstance(plan_action, str) or not isinstance(fill_action, str):
        return None
    if plan_action == fill_action:
        return 'same'
    plan_side = 'add' if plan_action in _ADD_SIDE else 'reduce' if plan_action in _REDUCE_SIDE else None
    fill_side = 'add' if fill_action in _ADD_SIDE else 'reduce' if fill_action in _REDUCE_SIDE else None
    if plan_side is None or fill_side is None:
        return 'other'
    return 'same' if plan_side == fill_side else 'opposite'


def build_decision_trace_scope(traces, workspace=None, limit=40):
    """What the trace card is allowed to claim about itself.

    The card used to sum its own 40-row window and print the result as an
    unqualified 已实现 total: $926.3 against a real US $2,347.68 + HK$7,259.16,
    and a flat "HK HK$0" while HK realized was HK$7,259.16 (#737). The window is
    a window; the totals have to come from the whole fill ledger and be labelled
    as such.
    @param traces - the (already capped) trace list the card will render.
    @returns dict of counts/totals, all with their denominators.
    """
    ws = workspace or WS_ROOT
    pf_doc = load_json(str(ws / 'portfolio.json')) or {}
    all_fills = 0
    realized_all = {}
    for leg in resolve_legs(pf_doc):
        for h in (pf_doc.get('portfolios') or {}).get(leg.bucket, {}).get('holdings', []):
            if not isinstance(h, dict):
                continue
            for tr in (h.get('trades') or []):
                if not isinstance(tr, dict) or not isinstance(tr.get('date'), str):
                    continue
                all_fills += 1
                if isinstance(tr.get('realized_pnl'), (int, float)):
                    realized_all[leg.currency] = realized_all.get(leg.currency, 0) + tr['realized_pnl']
    shown = list(traces or [])
    realized_shown = {}
    closed_shown = 0
    for t in shown:
        if isinstance(t.get('realizedPnl'), (int, float)):
            closed_shown += 1
            cur = t.get('currency')
            realized_shown[cur] = realized_shown.get(cur, 0) + t['realizedPnl']
    # T+1 verdicts per side, plus how many fills that side actually has. A fill
    # with no canonical close inside the window carries no verdict, so counting
    # only the judged ones would quietly shrink the denominator — the same move
    # #737 is about, one scale down (27 judged buys out of 28 in the window).
    verdicts = {}
    sides = {}
    for t in shown:
        side = 'reduce' if t.get('action') in _REDUCE_SIDE else 'add'
        sides[side] = sides.get(side, 0) + 1
        v = (t.get('t1') or {}).get('verdict')
        if v:
            verdicts.setdefault(side, {})
            verdicts[side][v] = verdicts[side].get(v, 0) + 1
    return {
        'fillsTotal': all_fills,
        'fillsShown': len(shown),
        'limit': limit,
        'closedShown': closed_shown,
        'realizedAll': {k: round(v, 2) for k, v in realized_all.items()},
        'realizedShown': {k: round(v, 2) for k, v in realized_shown.items()},
        'pairedShown': sum(1 for t in shown if t.get('decision')),
        'alignment': {
            key: sum(1 for t in shown if (t.get('decision') or {}).get('alignment') == key)
            for key in ('same', 'opposite', 'other')
        },
        # The mind/emotion layer the card advertises: 0 of 40 traces carried an
        # emotion in production. Shipping the coverage number keeps the gap
        # visible instead of silently rendering nothing (#738).
        'emotionShown': sum(1 for t in shown if (t.get('decision') or {}).get('emotion')),
        'mindShown': sum(1 for t in shown if (t.get('decision') or {}).get('thesis')),
        't1Verdicts': verdicts,
        't1Sides': sides,
        't1Shown': sum(1 for t in shown if t.get('t1')),
    }


def load_snapshots():
    """Returns recent-N snapshot summaries (NOT full holdings). Capped at MAX_SNAPSHOTS_EMBEDDED.

    Self-heals realized P&L: a snapshot's stored realized_pnl can lag the
    canonical trades[] ledger (the 2026-05-21 phantom-drawdown bug, where
    holdings were debited a day before realized caught up). We recompute the
    point-in-time realized reflected in each snapshot's own holdings and prefer
    it, so the equity curve / drawdown can never be poisoned by a stale aggregate
    even if a future writer regresses. Read-only on the snapshot files."""
    from clawock.portfolio.snapshots import realized_as_of, snapshot_shares
    ledger = _canonical_ledger()
    legs = _ledger_legs()
    paths = sorted(
        p for p in glob.glob(str(WS_ROOT / 'memory' / 'snapshots' / '*.json'))
        if SNAPSHOT_FNAME_RE.match(os.path.basename(p))
    )
    # Keep only the most recent N — chronological order so dashboard line chart still ascends
    paths = paths[-MAX_SNAPSHOTS_EMBEDDED:]
    results = []
    for p in paths:
        d = load_json(p)
        if not d:
            continue
        fname = os.path.basename(p)
        # filename: YYYY-MM-DD.json or YYYY-MM-DD-tag.json
        date = fname.split('.')[0].split('-')
        date = '-'.join(date[:3]) if len(date) >= 3 else fname
        pf = d.get('portfolios', {})
        books = {leg.key: pf.get(leg.bucket, {}) for leg in legs}
        vals = {k: (b.get('total_current_value', 0) or 0) for k, b in books.items()}
        reals = {k: (b.get('realized_pnl', 0) or 0) for k, b in books.items()}
        # Prefer point-in-time realized derived from the canonical ledger; only
        # override when it diverges from the stored value (stale/lagging snapshot).
        if SNAPSHOT_FNAME_RE.match(fname) and ledger:
            for leg in legs:
                region_pf = books[leg.key]
                if not region_pf:
                    continue
                true_real, _ = realized_as_of(
                    ledger.get(leg.bucket, []), date, snapshot_shares(region_pf),
                    market=leg.key)
                if abs(true_real - (reals[leg.key] or 0)) > 0.005:
                    reals[leg.key] = true_real
        row = {'date': date, 'file': fname}
        # Per-leg metrics first, one leg fully before the next — the payload is
        # serialized unsorted, so this grouping is the published field order.
        for leg in legs:
            book, val, real = books[leg.key], vals[leg.key], reals[leg.key]
            cost = book.get('total_cost', 0)
            row[f'{leg.key}_total_value'] = val
            row[f'{leg.key}_total_cost'] = cost
            row[f'{leg.key}_total_pnl'] = book.get('total_pnl', 0)
            row[f'{leg.key}_today_change'] = book.get('today_total_change', 0)
            row[f'{leg.key}_realized'] = real
            row[f'{leg.key}_equity'] = round(val + real, 2)
            # 总利润 = 浮盈 + 已实现 = equity − 成本基础. Unlike equity, this nets out
            # deployed capital, so its peak is the true P&L peak (market value peaks
            # when capital is MOST deployed, which is not the same as making the most
            # money — see the 5/16-vs-5/29 reconciliation). Uses the self-healed
            # realized so a lagging snapshot can't poison it either. NOTE: profit can
            # go negative, so % drawdown on this series is meaningless — only ever
            # report it in absolute money terms (the equity series owns the % axis).
            row[f'{leg.key}_profit'] = round(val + real - (cost or 0), 2)
        # 现金余额 (kcn 对账手填进 portfolio.json，refresh_today_snapshot 整文件拷进
        # 快照故自动留痕)。真实总资产 = total_value + cash。早于现金跟踪的快照为 None
        # → 前端 total-assets 曲线在该点断开(不瞎算)。US 自 2026-06-12 起有、HK 自 06-18 起有。
        # 字段名用币种,和账本里 `cash_usd`/`cash_hkd` 同一条规则。
        for leg in legs:
            row[f'{leg.key}_cash'] = books[leg.key].get(f'cash_{leg.currency.lower()}')
        # Market-session dates (≠ filename date) so daily P&L can collapse a US
        # session that straddles two HK-dated snapshots instead of double-counting.
        for leg in legs:
            row[f'{leg.key}_asof'] = _session_asof(books[leg.key], date[:4])
        results.append(row)
    return results


def load_plans():
    """Recent-N plan summaries. Large plans get trimmed to bullet list."""
    paths = sorted(glob.glob(str(WS_ROOT / 'memory' / '*-plan.json')))
    paths = paths[-MAX_PLANS_EMBEDDED:]
    results = []
    for p in paths:
        d = load_json(p)
        if not d:
            continue
        fname = os.path.basename(p)
        date = fname.replace('-plan.json', '')
        raw = json.dumps(d, ensure_ascii=False)
        if len(raw.encode('utf-8')) > MAX_PLAN_BYTES:
            # Plan too big — keep only top-level summary fields.
            actions = d.get('decisions') or []
            d = {
                'schema_version': 2,
                'date': d.get('date', date),
                'decisions_count': len(actions),
                'tldr': d.get('summary') or d.get('tldr') or '',
                'has_retrospective': bool(d.get('retrospective')),
                'context': d.get('context', {}),
                'truncated': True,
                'original_bytes': len(raw),
            }
        results.append({'date': date, 'file': fname, 'plan': d})
    return results


def total_plans_count():
    return len(glob.glob(str(WS_ROOT / 'memory' / '*-plan.json')))


_DEBATE_PASSIVE = {'hold_and_watch', 'watch', ''}


_ACTIVE_BUCKETS = {'cut', 'trim_on_rebound', 'add_only_on_trigger', 'add_on_breakout'}




def compute_debate_metrics(recent=20):
    """Does the multi-agent Tier1/2/3+Judge debate actually move anything? [cut #4]

    The debate costs ~3-5x the tokens of a single pass; its marginal value has
    never been measured. This quantifies its OUTPUT so the theater-vs-edge
    question becomes data-driven:
      - decisiveness  = share of actions that are active (cut/trim/add) vs the
        risk_on default of HOLD. ~all-HOLD means the debate reproduced a one-line
        rule at 5x the cost.
      - contested_rate = share of actions the Judge marked as genuinely contested
        (Bull vs Bear disagreed). Null until plans start carrying the flag; pairs
        with calibration to later test 'do contested calls calibrate better?'.
    """
    paths = sorted(glob.glob(str(WS_ROOT / 'memory' / '*-plan.json')))[-recent:]
    n_actions = n_active = n_contested = n_contested_known = 0
    n_debate = n_bear = n_attacked = n_frames = n_cited = 0
    buckets = {}
    plans_n = 0
    for p in paths:
        try:
            d = json.loads(Path(p).read_text())
        except Exception:
            continue
        acts = d.get('decisions') or []
        if not acts:
            continue
        plans_n += 1
        for a in acts:
            b = (a.get('action') or '').strip()
            n_actions += 1
            buckets[b] = buckets.get(b, 0) + 1
            if b not in _DEBATE_PASSIVE:
                n_active += 1
            c = a.get('contested')
            if isinstance(c, bool):
                n_contested_known += 1
                n_contested += 1 if c else 0
            # `contested` is the debate's verdict compressed to one bit; these
            # count whether the debate itself was recorded (#1117). A claim that
            # both sides were argued is checkable only if the losing side is on
            # the page, so `bear` is counted separately from "any block".
            debate = a.get('debate')
            if isinstance(debate, dict) and debate:
                n_debate += 1
                if debate.get('evidence_ids'):
                    n_cited += 1
                if str(debate.get('bear') or '').strip():
                    n_bear += 1
                if str(debate.get('attacked_consensus') or '').strip():
                    n_attacked += 1
                if debate.get('frames'):
                    n_frames += 1
    if not n_actions:
        return None
    return {
        'plans': plans_n,
        'decisions': n_actions,
        'decisiveness_pct': round(100 * n_active / n_actions, 1),
        'action_dist': dict(sorted(buckets.items(), key=lambda kv: -kv[1])),
        'contested_rate': (round(n_contested / n_contested_known, 3)
                           if n_contested_known else None),
        'contested_coverage': n_contested_known,
        # Stage 1 of #1117 is deliberately un-gated: the field is optional, so
        # this series is what says whether the structure is actually being
        # emitted. It is the evidence a later required-field gate should be
        # argued from.
        'debate_coverage': {
            'decisions': n_actions,
            'with_debate': n_debate,
            'with_evidence_ids': n_cited,
            'with_bear_case': n_bear,
            'with_attacked_consensus': n_attacked,
            'with_frames': n_frames,
            'bear_case_pct': round(100 * n_bear / n_actions, 1) if n_actions else None,
        },
        'note': ('辩论产出量化：decisiveness 低=risk_on 里 Judge 大多回 HOLD，'
                 '一行默认规则即可复现，3-5x token 的辩论边际可疑。contested_rate '
                 '待 plan 开始标记后，与 calibration 联合检验「被争议的 call 是否校准更好」。'
                 'debate_coverage 量的是另一件事：辩论本身有没有留下可核对的结构'
                 '（反方案文、被攻击的共识、Judge frame），而不是它得出了什么结论。'),
    }


def compute_magnitude_metrics(rows=None):
    """Was the size of the move right, not just its direction? (#1159)

    The book grades direction (`evaluation.outcome`) and grades how sure it was
    (`confidence`, prequentially, by Brier). It has never graded **how far** —
    QuantConnect's `InsightScore` calls that leg Magnitude, and porting it was
    closed once on the grounds that it would need a new required field on every
    decision. It does not: the field is optional, and this is the series that
    says whether it is being written, exactly as `debate_coverage` did for
    #1117.

    Scored at t1 only, and deliberately against `underlying_return_t1_pct`
    rather than `benefit_t1_pct`. Benefit is measured against a counterfactual —
    it answers "was acting better than not acting" — while a forecast of "this
    falls 8%" is a claim about the name, so the name's own return is the only
    honest counterpart. t5 and t20 have no underlying-return column to compare
    against, so they are not scored rather than scored against the wrong number.

    `mean_error_pct` is signed and is the interesting one: a book that is right
    about direction and systematically too dramatic about size has a positive
    bias here and a fine hit rate, and no existing number on this dashboard
    would show it.
    """
    if rows is None:
        rows = decision_v2.load_decisions(WS_ROOT / 'memory' / 'decisions.jsonl')
    scored, absolute, signed, agreed = 0, [], [], 0
    stated = 0
    for row in rows:
        expected = row.get('expected_move_pct')
        if expected is not None:
            stated += 1
        evaluation = row.get('evaluation') or {}
        realized = evaluation.get('underlying_return_t1_pct')
        if expected is None or realized is None:
            continue
        if evaluation.get('status') != 'settled':
            continue
        scored += 1
        absolute.append(abs(float(expected) - float(realized)))
        signed.append(float(expected) - float(realized))
        if (float(expected) >= 0) == (float(realized) >= 0):
            agreed += 1
    return {
        'decisions': len(rows),
        'with_expected_move': stated,
        'coverage_pct': round(100 * stated / len(rows), 1) if rows else None,
        'scored_t1': scored,
        'mean_abs_error_pct': round(statistics.fmean(absolute), 3) if absolute else None,
        'mean_error_pct': round(statistics.fmean(signed), 3) if signed else None,
        'direction_agreement': round(agreed / scored, 3) if scored else None,
        'note': ('幅度校准（#1159）：`expected_move_pct` 是选填字段，这条先是覆盖率序列 —— '
                 '和 #1117 的 debate 一样，必填与否要对着序列谈，不是对着愿望谈。'
                 '只在 t1 打分，且对的是 `underlying_return_t1_pct`（这只票自己的收益）'
                 '而不是 `benefit_t1_pct`（相对不动的反事实）：'
                 '「预期跌 8%」是关于这只票的断言，拿反事实去对它是对错了东西。'
                 'mean_error_pct 带符号：方向对、幅度系统性夸大的账本，'
                 '命中率好看而这个数为正，现有的任何一个指标都看不出来。'),
    }


def total_snapshots_count():
    return sum(
        1 for p in glob.glob(str(WS_ROOT / 'memory' / 'snapshots' / '*.json'))
        if SNAPSHOT_FNAME_RE.match(os.path.basename(p))
    )


# ── Dashboard v2 NEW field computers ─────────────────────────────────────
# Each function MUST swallow internal exceptions and return its empty/null
# default so a partial failure can't take down the whole dashboard build.

def _pct_change(curr, prev):
    """(curr - prev) / prev * 100, rounded to 2 decimals; None if prev <= 0 or invalid."""
    try:
        if prev is None or curr is None:
            return None
        prev = float(prev)
        if prev <= 0:
            return None
        return round((float(curr) - prev) / prev * 100, 2)
    except Exception:
        return None


def compute_delta(snapshots, legs=None):
    """Equity rolling-window % change vs today, per leg.

    snapshots is the same list build_dashboard already prepares: ascending date,
    so today = snapshots[-1], yesterday = snapshots[-2], etc. Each row carries
    `<leg>_equity`, written by `load_snapshots` from the same leg list.
    """
    legs = _ledger_legs() if legs is None else legs
    empty = {leg.key: {'today_pct': None, '7d_pct': None, '30d_pct': None}
             for leg in legs}
    try:
        if not snapshots:
            return empty
        n = len(snapshots)
        today = snapshots[-1]

        def at(offset_back, key):
            idx = n - 1 - offset_back
            if idx < 0:
                return None
            return snapshots[idx].get(key)

        def region(value_key):
            today_v = today.get(value_key)
            return {
                'today_pct': _pct_change(today_v, at(1, value_key)) if n >= 2 else None,
                '7d_pct':    _pct_change(today_v, at(7, value_key)) if n >= 8 else None,
                '30d_pct':   _pct_change(today_v, at(30, value_key)) if n >= 31 else None,
            }
        return {leg.key: region(f'{leg.key}_equity') for leg in legs}
    except Exception as e:
        print(f'  warn: compute_delta failed: {e}', file=sys.stderr)
        return empty


def compute_today_movers(us_h, hk_h, leg_keys=('us', 'hk')):
    """abs(today_change_pct) >= 3.0 holdings across both legs, top 10 by abs.

    `leg_keys` labels the two holdings lists. The default is the historical pair
    and exists for direct callers; the projection passes its ledger's legs.
    """
    try:
        items = []
        for leg_key, holdings in zip(leg_keys, (us_h, hk_h)):
            for h in (holdings or []):
                pct = h.get('today_change_pct')
                if pct is None:
                    continue
                if abs(pct) >= 3.0:
                    items.append({
                        'ticker': h.get('ticker'),
                        'name': h.get('name', ''),
                        'region': leg_key,
                        'today_change_pct': round(pct, 2),
                        'current_price': h.get('current_price'),
                    })
        items.sort(key=lambda x: -abs(x['today_change_pct']))
        return items[:10]
    except Exception as e:
        print(f'  warn: compute_today_movers failed: {e}', file=sys.stderr)
        return []


def _latest_brief_context():
    """Return (path, dict) of newest memory/.tmp/brief-context-*.json by mtime, or (None, None)."""
    try:
        paths = glob.glob(str(WS_ROOT / 'memory' / '.tmp' / 'brief-context-*.json'))
        if not paths:
            return None, None
        latest = max(paths, key=os.path.getmtime)
        return latest, load_json(latest)
    except Exception as e:
        print(f'  warn: _latest_brief_context failed: {e}', file=sys.stderr)
        return None, None


def load_previous_payload(path):
    """Return `(payload_or_None, missing)` for a previously published dashboard.

    `path` is an explicit input, not an ambient lookup: the values this file
    contributes are the only part of the output that does not come from the
    workspace, so which file supplied them has to be a stated argument and is
    reported in `build_status.previous_payload` (#262). `path is None` means the
    caller asked for a build that depends on nothing but the workspace.

    `missing` separates the two ways of getting `None`, which used to be the same
    thing (#314). A caller that NAMED a file and did not get it is not doing a
    workspace-only build — it is doing a degraded one, and until now that was
    silent: `preserved: []` looks identical whether every source was present or
    the recovery payload simply was not there. The one caller where the flag does
    anything is brief-fallback, whose whole job is recovery, so the day the path
    stops resolving is the day recovery stops with nothing to show for it.

    Deliberately not fatal. A missing recovery payload must not block a publish —
    detect, do not silence, and do not turn a degraded build into no build.
    """
    if path is None:
        return None, False
    try:
        path = Path(path)
        if path.exists():
            return load_json(str(path)), False
        print(f'  warn: --previous {path} does not exist — no card can be restored '
              f'from it; this build is workspace-only despite being asked for a '
              f'recovery source', file=sys.stderr)
        return None, True
    except Exception as e:
        print(f'  warn: load_previous_payload({path}) failed: {e}', file=sys.stderr)
        return None, True


def merge_previous_payload(out, previous, presence, usable=None):
    """Fill in `out` keys whose source context was absent from this checkout.

    A context-less rebuild (memory/.tmp is gitignored, so brief-context and the
    insights / intraday sidecars are ABSENT — meaning "not in THIS checkout",
    NOT "no insight today") must not blank the cards the last build published,
    or Pages flickers empty. `presence[key]` is False for exactly that case, and
    the last non-empty published value is restored.

    `usable[key]` overrides what counts as a value worth restoring. Truthiness is
    the default, but `peer_divergence` is a wrapper dict that is truthy even when
    its `items` list is empty, and republishing an empty card is not preservation.

    Returns the sorted keys taken from `previous`, which is what makes this
    dependency measurable rather than invisible: on the live host every source
    is present, so the correct value is `[]`.
    """
    taken = []
    for key, source_present in presence.items():
        if source_present:
            continue
        value = (previous or {}).get(key)
        if ((usable or {}).get(key) or bool)(value):
            out[key] = value
            taken.append(key)
    return sorted(taken)


def workspace_relative(path):
    """Path as written inside the workspace, so a published value does not carry
    the absolute location of whichever machine built it.

    `/root/.openclaw/workspace/assets/data/dashboard.json` on the live host and
    `/home/runner/work/clawock/clawock/assets/data/dashboard.json` on an Actions
    runner name the same input; publishing the raw string would make the two
    publishers alternate a field that `semantic_value()` does not strip, i.e.
    a real commit for no reader-visible change.
    """
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(Path(WS_ROOT).resolve()))
    except (ValueError, OSError):
        return str(path)


PRESERVE_ABSENT_PREFIX = 'preserve-absent-'


def record_preservation(presence, taken, source, out_file, at=None, missing=False):
    """Append one line per build to memory/.tmp/preserve-absent-YYYY-MM-DD.jsonl.

    The merge has exactly one known publishing consumer: `brief-fallback.yml`
    runs `brief_postflight`, which rebuilds and commits the dashboard from an
    Actions checkout. `brief_preflight` writes a brief-context there, but the
    off-host generator writes no insights / intraday / sector-scan sidecars, so
    those cards would publish blank without the merge — the 2026-06-21
    regression. The scans stopped rebuilding dashboard.json on 2026-07-04
    (gha_commit_push.sh header) and the other two Actions builders never commit.

    What is not known is how much else reaches it: the pre-commit hook rebuilds
    on any `portfolio.json` commit, and a developer clone has no memory/.tmp
    either. So this measures rather than assumes, and records the empty case too,
    so "it has not fired in N days" has a denominator.

    One file per day, because `gc_sessions` ages memory/.tmp out by whole-file
    mtime (KEEP_TMP_DAYS=14) — a single append-only file refreshes its own mtime
    on every build and would never be collected.

    Deliberately not in the payload and deliberately not created if the directory
    is absent — memory/.tmp is gitignored and only exists on a real workspace.
    Never raises: measurement must not be able to fail a publish.
    """
    try:
        tmp_dir = Path(WS_ROOT) / 'memory' / '.tmp'
        if not tmp_dir.is_dir():
            return
        at = at or datetime.now(timezone.utc)
        line = json.dumps({
            'at': at.isoformat(timespec='seconds'),
            'out_file': str(out_file),
            # Absolute here on purpose: unlike the published field, this file is
            # local and knowing which checkout built it is the point.
            'previous_source': str(source) if source else None,
            'previous_missing': missing,
            'absent_sources': sorted(k for k, present in presence.items() if not present),
            'preserved': taken,
        }, ensure_ascii=False)
        daily = tmp_dir / f'{PRESERVE_ABSENT_PREFIX}{at.date().isoformat()}.jsonl'
        with daily.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    except Exception as e:
        print(f'  warn: preservation telemetry failed: {e}', file=sys.stderr)


def load_sector_scan():
    """Read the freshest sector-scan-*.json written by daily-deep-brief LLM.

    LLM writes today's sector overview (theme / top movers / self position /
    attribution / narrative) to memory/.tmp/sector-scan-{date}.json after
    running Step 3 板块全景 tavily-search. We pick the newest by mtime to
    cover overnight edge cases. Non-fatal on any error (returns {}).
    """
    try:
        paths = glob.glob(str(WS_ROOT / 'memory' / '.tmp' / 'sector-scan-*.json'))
        if not paths:
            return {}
        latest = max(paths, key=os.path.getmtime)
        data = load_json(latest)
        if not isinstance(data, dict):
            return {}
        # Stamp where it came from so frontend can show "as of {date}"
        data.setdefault('_source', os.path.basename(latest))
        return data
    except Exception as e:
        print(f'  warn: load_sector_scan failed: {e}', file=sys.stderr)
        return {}


def load_tmp_sidecar(prefix, max_age_days=None):
    """Freshest memory/.tmp/{prefix}-*.json by mtime, stamped with _source + _stale.

    Used for LLM-narrative sidecars the cron AGENT writes during Step 3 (behavioral
    review / bear cases / status banner / movers attribution). The LLM runs inside
    the gateway/GHA where API keys live — those keys NEVER touch these files or
    dashboard.json (published to public Pages), only the narrative text does.
    Non-fatal on any error. If max_age_days is set, marks _stale=True when the
    file's mtime is older, so the frontend can grey it out instead of showing
    day-old critique as if it were current.

    Hand-authored JSON goes through json_repair: on 2026-07-28 a single missing
    closing quote cost the whole behavioural-review card group. A repair is
    reported on stderr as `repair:` — deliberately not `warn:`, because the
    section did render and the build is not degraded — but it is still reported,
    because a producer shipping invalid JSON every morning is a bug.

    Anything short of "there is no sidecar in this checkout" returns
    `{'_source': ..., '_invalid': True}` rather than `{}`. The difference
    matters: callers pass `bool(result)` to `_preserve_absent`, and an empty dict
    means "this checkout has no sidecar" — which republishes *yesterday's* card.
    Only proven absence may do that. A file we found but could not read, and even
    a directory listing that failed outright, are both uncertainty, not absence.
    """
    name = None
    try:
        paths = glob.glob(str(WS_ROOT / 'memory' / '.tmp' / f'{prefix}-*.json'))
    except Exception as e:
        # Cannot even enumerate: we do not know whether a sidecar exists, so we
        # must not claim it is absent.
        print(f'  warn: load_tmp_sidecar({prefix}) could not list: {e}', file=sys.stderr)
        return {'_source': None, '_invalid': True}
    if not paths:
        return {}
    try:
        latest = max(paths, key=os.path.getmtime)
        name = os.path.basename(latest)
        data, repairs, status = json_repair.load_json_repaired(latest)
        if status == json_repair.REPAIRED:
            print(f'  repair: {name} — {json_repair.describe(repairs, status)}',
                  file=sys.stderr)
        elif status != json_repair.CLEAN:
            print(f'  warn: failed to load {latest}: '
                  f'{json_repair.describe(repairs, status)}', file=sys.stderr)
            return {'_source': name, '_invalid': True}
        if not isinstance(data, dict):
            print(f'  warn: {name}: top level is {type(data).__name__}, not object',
                  file=sys.stderr)
            return {'_source': name, '_invalid': True}
        data.setdefault('_source', name)
        if max_age_days is not None:
            age_days = (time.time() - os.path.getmtime(latest)) / 86400.0
            data['_stale'] = age_days > max_age_days
        return data
    except Exception as e:
        print(f'  warn: load_tmp_sidecar({prefix}) failed: {e}', file=sys.stderr)
        # Reached only with `paths` non-empty, so a sidecar does exist and we
        # failed to read it — bad encoding, an I/O error, or an mtime that could
        # not be stat'd. Every one of those is untrustworthy, never absent.
        return {'_source': name, '_invalid': True}


_REVIEW_TAGS = {'edge', 'bias', 'warning'}
_SUSPECT_DOLLAR = re.compile(r'[\$＄]\s?\d')  # raw $amount


def _clean_str(v, maxlen):
    """Return a trimmed, length-capped non-empty str, else None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s[:maxlen] if s else None


# A bear_case may cover two or three holdings at once (paired thesis on e.g. two
# leveraged names in the same sector), which the agent writes as `RKLX+SPCH`.
_COMPOSITE_SEP = re.compile(r'[+/&,]')
_MAX_COMPOSITE_PARTS = 3


def _resolve_insight_ticker(raw, known_tickers):
    """Resolve a bear_case ticker label against live holdings.

    Accepts a composite label (`A+B`) as long as EVERY component is a real
    holding — the membership check exists to block names that aren't in the book
    at all, not to block formatting. Returns the normalised `A+B` label, or None
    if any component is unknown (→ caller drops the entry, guard unchanged).
    """
    if not raw:
        return None
    parts = [p.strip() for p in _COMPOSITE_SEP.split(raw)]
    parts = [p for p in parts if p]
    if not parts or len(parts) > _MAX_COMPOSITE_PARTS:
        return None
    if known_tickers and any(p not in known_tickers for p in parts):
        return None
    return '+'.join(parts)


def validate_insights(data, known_tickers):
    """Schema + sanity gate for the agent-written daily insights sidecar.

    The sidecar is LLM-authored, so anything malformed or hallucinated must be
    DROPPED here (→ card hides) rather than published to the public dashboard.json.
    Bad entries are dropped individually; a field only survives if its core content
    is present and sane. `known_tickers` (live holdings) blocks bear_cases on names
    that aren't even in the book. Returns the cleaned, render-ready dict.
    """
    out = {'behavioral_review': None, 'bear_cases': [], 'hidden_concentration': None}
    if not isinstance(data, dict):
        return out
    # behavioral_review — verdict + tagged points; calibration is %-based, so a raw
    # $amount in a review point is a hallucination → drop that point.
    br = data.get('behavioral_review')
    if isinstance(br, dict):
        verdict = _clean_str(br.get('verdict'), 120)
        pts = []
        for p in (br.get('points') or [])[:8]:
            if not isinstance(p, dict):
                continue
            txt = _clean_str(p.get('text'), 220)
            if not txt:
                continue
            if _SUSPECT_DOLLAR.search(txt):
                print(f'  warn: insights dropped review point w/ suspect $amount: {txt[:42]}', file=sys.stderr)
                continue
            tag = (p.get('tag') or '').strip().lower()
            pts.append({'text': txt, 'tag': tag if tag in _REVIEW_TAGS else 'bias'})
        if verdict and pts:
            out['behavioral_review'] = {'verdict': verdict, 'points': pts}
    # bear_cases — ticker must be a real holding
    for c in (data.get('bear_cases') or [])[:5]:
        if not isinstance(c, dict):
            continue
        # Cap allows a composite label (`A+B`); the real guard is the
        # per-component holdings check in _resolve_insight_ticker.
        tk = _clean_str(c.get('ticker'), 40)
        thesis = _clean_str(c.get('thesis'), 220)
        if not tk or not thesis:
            continue
        resolved = _resolve_insight_ticker(tk, known_tickers)
        if not resolved:
            print(f'  warn: insights dropped bear_case for unknown ticker {tk}', file=sys.stderr)
            continue
        out['bear_cases'].append({
            'ticker': resolved,
            'thesis': thesis,
            'falsifier': _clean_str(c.get('falsifier'), 160) or '',
            'watch': _clean_str(c.get('watch'), 120) or '',
        })
    # hidden_concentration — needs headline + a plausible 0-100 exposure_pct
    hc = data.get('hidden_concentration')
    if isinstance(hc, dict):
        headline = _clean_str(hc.get('headline'), 120)
        try:
            pct = float(hc.get('exposure_pct'))
        except (TypeError, ValueError):
            pct = None
        if headline and pct is not None and 0 <= pct <= 100:
            out['hidden_concentration'] = {
                'headline': headline,
                'factor': _clean_str(hc.get('factor'), 40) or '',
                'exposure_pct': round(pct),
                'detail': _clean_str(hc.get('detail'), 220) or '',
            }
    return out


def validate_intraday_insights(data, known_tickers):
    """Schema + sanity gate for the intraday sidecar (status_banner + per-mover
    attribution). Mover notes only survive for tickers that actually exist in the
    book. Returns {status_banner, movers}."""
    out = {'status_banner': None, 'movers': {}}
    if not isinstance(data, dict):
        return out
    out['status_banner'] = _clean_str(data.get('status_banner'), 160)
    mv = data.get('movers')
    if isinstance(mv, dict):
        for tk, note in mv.items():
            tkc = _clean_str(tk, 12)
            notec = _clean_str(note, 120)
            if not tkc or not notec:
                continue
            if known_tickers and tkc not in known_tickers:
                continue
            out['movers'][tkc] = notec
    return out


# Tickers we treat as leveraged ETFs even when context doesn't tag them.
_LEVERAGED_TICKERS = instrument_registry.leveraged_symbols()


def extract_anomalies(brief_ctx, us_h, hk_h, leg_keys=None):
    """Risk signals derived from the latest brief-context.

    Recognized types:
      - rsi_overbought          (rsi >= 70 in any embedded indicator block)
      - peer_divergence         (divergence_signal present, severity by gap pp)
      - high_weight_loss        (concentration weight >= 25% AND holding pnl_percent <= -10)
      - leveraged_etf_stop      (leveraged ticker w/ self_pnl_pct <= -15 OR today_change_pct <= -8)
      - no_context              (single entry, fallback when no context file found)
    """
    try:
        if not brief_ctx:
            return [{
                'type': 'no_context',
                'ticker': '',
                'detail': 'no brief-context-*.json found in memory/.tmp/',
                'severity': 'low',
            }]
        out = []
        holdings_by_ticker = {}
        for h in (us_h or []):
            holdings_by_ticker[str(h.get('ticker') or '').upper()] = h
        for h in (hk_h or []):
            holdings_by_ticker[str(h.get('ticker') or '')] = h

        # NOTE: peer_divergence is no longer injected into anomalies. It now has
        # its own 『同行背离 Peer Divergence』card (Market tab) fed by the single
        # source extract_peer_divergence() below — avoids the old double-compute +
        # the UI-layer filter that hid it. holdings_by_ticker above is still used
        # by the high_weight_loss / leveraged guards.

        # high_weight_loss anomalies (concentration top tickers w/ deep loss)
        conc = brief_ctx.get('concentration') or {}
        # Leg order comes from the caller's ledger, NOT from `conc`: this loop
        # appends to `out` and nothing sorts it afterwards, so the iteration order
        # is the published order of the anomaly list. The brief-context happens to
        # carry its concentration keys as ['hk', 'us'] — reading them in that order
        # would silently reorder the card the day both legs have an entry.
        for region in (leg_keys or list(conc)):
            if region not in conc:
                continue
            region_conc = conc.get(region) or {}
            weights = region_conc.get('weights') or []
            for w in weights:
                tk = str(w.get('ticker') or '')
                weight_pct = w.get('weight_pct') or 0
                if weight_pct < 25:
                    continue
                h = holdings_by_ticker.get(tk.upper()) or holdings_by_ticker.get(tk)
                if not h:
                    continue
                pnl_pct = h.get('pnl_percent')
                if pnl_pct is not None and pnl_pct <= -10:
                    sev = 'high' if (weight_pct >= 40 or pnl_pct <= -20) else 'medium'
                    out.append({
                        'type': 'high_weight_loss',
                        'ticker': tk,
                        'detail': f'weight {weight_pct:.1f}% + pnl {pnl_pct:.1f}%',
                        'severity': sev,
                    })

        # leveraged_etf_stop anomalies — read from the same brief peer_scan snapshot as
        # extract_peer_divergence(). The peer_divergence refactor (3f507d3) dropped this
        # definition but left the loop, so the whole function raised NameError and silently
        # produced no anomalies. (2026-05-30 fix)
        peer_scan = brief_ctx.get('peer_scan') or {}
        peer_items = peer_scan.items() if isinstance(peer_scan, dict) else []
        for ticker, v in peer_items:
            tk_str = str(ticker or '').upper()
            if tk_str not in _LEVERAGED_TICKERS:
                continue
            if not isinstance(v, dict):
                continue
            # 优先用 portfolio 实时 pnl/today，brief peer_scan 快照可能陈旧（5/28 错位价残留会触发假止损）。
            h_live = holdings_by_ticker.get(tk_str) or holdings_by_ticker.get(str(ticker))
            if isinstance(h_live, dict) and h_live.get('pnl_percent') is not None:
                self_pnl = h_live.get('pnl_percent')
                self_today = h_live.get('today_change_pct')
            else:
                self_pnl = v.get('self_pnl_pct')
                self_today = v.get('self_pct_1d')
            triggered = False
            detail_bits = []
            if isinstance(self_pnl, (int, float)) and self_pnl <= -15:
                triggered = True
                detail_bits.append(f'pnl {self_pnl:.1f}%')
            if isinstance(self_today, (int, float)) and self_today <= -8:
                triggered = True
                detail_bits.append(f'today {self_today:.1f}%')
            if triggered:
                sev = 'high' if (isinstance(self_pnl, (int, float)) and self_pnl <= -25) else 'medium'
                out.append({
                    'type': 'leveraged_etf_stop',
                    'ticker': str(ticker),
                    'detail': 'leveraged ETF: ' + ', '.join(detail_bits),
                    'severity': sev,
                })

        # rsi_overbought — only fire if brief_ctx carries an rsi block; current
        # context files don't, but keep the scanner so future preflight runs work.
        def _scan_rsi(node):
            if isinstance(node, dict):
                tk = node.get('ticker') or node.get('symbol')
                rsi = node.get('rsi') or node.get('rsi_14') or node.get('RSI')
                if tk and isinstance(rsi, (int, float)) and rsi >= 70:
                    out.append({
                        'type': 'rsi_overbought',
                        'ticker': str(tk),
                        'detail': f'RSI {rsi:.1f} >= 70',
                        'severity': 'high' if rsi >= 80 else 'medium',
                    })
                for v in node.values():
                    _scan_rsi(v)
            elif isinstance(node, list):
                for it in node:
                    _scan_rsi(it)
        try:
            _scan_rsi(brief_ctx.get('us_fundamentals'))
            _scan_rsi(brief_ctx.get('indicators'))
        except Exception:
            pass

        return out
    except Exception as e:
        print(f'  warn: extract_anomalies failed: {e}', file=sys.stderr)
        return []


def extract_peer_divergence(brief_ctx, us_h=None, hk_h=None):
    """List of divergence_signal=true peer scan rows from brief context.

    与 extract_anomalies 同源（都读 brief peer_scan 快照），故套同样的实时守卫：
    peer 报价缺失(0.0) 或快照 self 与 portfolio 实时 today_change 符号相反 → 跳过，
    避免 5/28 错位价残留泄漏到 dashboard 的背离卡。
    """
    try:
        if not brief_ctx:
            return []
        holdings_by_ticker = {}
        for h in (us_h or []):
            holdings_by_ticker[str(h.get('ticker') or '').upper()] = h
        for h in (hk_h or []):
            holdings_by_ticker[str(h.get('ticker') or '')] = h
        peer_scan = brief_ctx.get('peer_scan') or {}
        if isinstance(peer_scan, dict):
            items = peer_scan.items()
        elif isinstance(peer_scan, list):
            items = [(p.get('ticker'), p) for p in peer_scan]
        else:
            return []
        out = []
        for ticker, v in items:
            if not isinstance(v, dict):
                continue
            if not v.get('divergence_signal'):
                continue
            self_pct = v.get('self_pct_1d')
            best_peer = None
            best_peer_name = None
            peer_pct = None
            best_gap = None
            for p in (v.get('listed_peers') or []):
                pp = p.get('pct_1d')
                if pp is None or self_pct is None:
                    continue
                gap = pp - self_pct  # peer beating self → positive
                if best_gap is None or abs(gap) > abs(best_gap):
                    best_gap = gap
                    best_peer = p.get('ticker')
                    best_peer_name = p.get('name')
                    peer_pct = pp
            try:
                self_pct_v = round(float(self_pct), 2) if self_pct is not None else None
            except Exception:
                self_pct_v = None
            try:
                peer_pct_v = round(float(peer_pct), 2) if peer_pct is not None else None
            except Exception:
                peer_pct_v = None
            try:
                div_pp = round(float(best_gap), 2) if best_gap is not None else None
            except Exception:
                div_pp = None
            # 实时守卫（同 extract_anomalies）：peer 报价缺失(0.0) 或快照陈旧(与实时今日反号) → 跳过
            if peer_pct_v == 0.0:
                continue
            h_live = holdings_by_ticker.get(str(ticker).upper()) or holdings_by_ticker.get(str(ticker))
            live_today = h_live.get('today_change_pct') if isinstance(h_live, dict) else None
            if (isinstance(live_today, (int, float)) and isinstance(self_pct_v, (int, float))
                    and live_today * self_pct_v < 0 and abs(live_today - self_pct_v) >= 4):
                continue
            out.append({
                'ticker': str(ticker),
                'self_pct_1d': self_pct_v,
                'best_peer': best_peer or '',
                'best_peer_name': best_peer_name or '',
                'peer_pct_1d': peer_pct_v,
                'divergence_pp': div_pp,
            })
        return out
    except Exception as e:
        print(f'  warn: extract_peer_divergence failed: {e}', file=sys.stderr)
        return []


def compute_weight_confidence(portfolio, window_days=30):
    """Per-ticker current_weight × avg_confidence (last N days), to spot
    'high weight + low confidence' red flags at a glance.
    Output: list[{ticker, region, weight_pct, avg_confidence, n_actions, quadrant}]
    quadrant ∈ {high_risk, conviction, low_conv_small, comfort}:
      high_risk      = weight ≥ 0.20 AND conf < 0.65   ← user's red zone
      conviction     = weight ≥ 0.20 AND conf ≥ 0.65
      low_conv_small = weight < 0.20 AND conf < 0.65
      comfort        = weight < 0.20 AND conf ≥ 0.65
    """
    try:
        rows = decision_v2.episode_representatives(decision_v2.load_decisions(), 't1')
        today = datetime.now(timezone.utc).date()
        # Aggregate avg confidence per ticker over window
        conf_acc = {}  # ticker -> [sum, count]
        for r in rows:
            try:
                pd = datetime.strptime(r.get('plan_date', '')[:10], '%Y-%m-%d').date()
            except Exception:
                continue
            if (today - pd).days > window_days:
                continue
            tk = (r.get('ticker') or '').strip()
            c = decision_v2._float(r.get('confidence'))
            if not tk or c is None:
                continue
            acc = conf_acc.setdefault(tk, [0.0, 0])
            acc[0] += c
            acc[1] += 1

        # Compute per-region weights from active holdings
        out = []
        for leg in resolve_legs(portfolio):
            region_label = leg.key
            pf = (portfolio.get('portfolios') or {}).get(leg.bucket, {}) or {}
            holdings = [h for h in pf.get('holdings', []) if (h.get('shares') or 0) > 0]
            total = sum((h.get('current_value') or 0) for h in holdings)
            if total <= 0:
                continue
            for h in holdings:
                tk = h.get('ticker') or h.get('code')
                if not tk:
                    continue
                weight = (h.get('current_value') or 0) / total
                acc = conf_acc.get(tk)
                avg_c = round(acc[0] / acc[1], 3) if acc and acc[1] > 0 else None
                n = acc[1] if acc else 0
                # quadrant only meaningful when we have a confidence reading
                if avg_c is None:
                    quad = 'no_data'
                elif weight >= 0.20 and avg_c < 0.65:
                    quad = 'high_risk'
                elif weight >= 0.20:
                    quad = 'conviction'
                elif avg_c < 0.65:
                    quad = 'low_conv_small'
                else:
                    quad = 'comfort'
                out.append({
                    'ticker': tk,
                    'region': region_label,
                    'weight_pct': round(weight * 100, 2),
                    'avg_confidence': avg_c,
                    'n_actions': n,
                    'quadrant': quad,
                })
        # Sort: high_risk first, then by weight desc
        rank = {'high_risk': 0, 'conviction': 1, 'low_conv_small': 2, 'comfort': 3, 'no_data': 4}
        out.sort(key=lambda x: (rank.get(x['quadrant'], 9), -x['weight_pct']))
        return out
    except Exception as e:
        print(f'  warn: compute_weight_confidence failed: {e}', file=sys.stderr)
        return []


def compute_plan_timeline(plans, limit=15):
    """V2 strategy-aware decision timeline, most recent first."""
    try:
        out = []
        rows = sorted(decision_v2.load_decisions(),
                      key=lambda d: (d.get('created_at', ''), d.get('decision_id', '')), reverse=True)
        for d in rows[:limit]:
            ev, ex, cond, size = (d.get('evaluation') or {}, d.get('execution') or {},
                                  d.get('condition') or {}, d.get('size') or {})
            out.append({
                'date': d.get('plan_date'), 'decision_id': d.get('decision_id'),
                'episode_id': d.get('episode_id'), 'ticker': d.get('ticker'),
                'strategy_id': d.get('strategy_id'), 'action': d.get('action'),
                'condition': cond, 'size': size, 'confidence': d.get('confidence'),
                'rationale': d.get('rationale'), 'status': ev.get('status'),
                'outcome': ev.get('outcome'), 'benefit_t1_pct': ev.get('benefit_t1_pct'),
                'execution': ex.get('status', 'unknown'), 'override': d.get('override'),
            })
        return out
    except Exception as e:
        print(f'  warn: compute_plan_timeline failed: {e}', file=sys.stderr)
        return []


def _series_extremes(series):
    """series = list of (date, value). Returns all-time peak / trough and the
    worst peak-to-trough drawdown (with the dates that bracket it).

    `current` is the last point; `current_dd_pct` is its retracement from the
    running peak; `at_low` flags that today IS the lowest point in the series.
    """
    pts = [(d, float(v)) for d, v in series if v is not None]
    if not pts:
        return None
    peak = pts[0][1]
    peak_date = pts[0][0]
    dd_peak_date = peak_date          # peak that precedes the worst trough
    worst = 0.0
    worst_trough_date = pts[0][0]
    worst_peak_date = pts[0][0]
    for d, v in pts:
        if v > peak:
            peak = v
            peak_date = d
        if peak > 0:
            dd = (v - peak) / peak * 100
            if dd < worst:
                worst = dd
                worst_trough_date = d
                worst_peak_date = peak_date
    hi = max(pts, key=lambda x: x[1])
    lo = min(pts, key=lambda x: x[1])
    cur_date, cur = pts[-1]
    cur_dd = round((cur - peak) / peak * 100, 2) if peak > 0 else None
    peak_at_worst = next((v for d, v in pts if d == worst_peak_date), None)
    trough_at_worst = next((v for d, v in pts if d == worst_trough_date), None)
    max_dd_abs = (round(peak_at_worst - trough_at_worst, 2)
                  if peak_at_worst is not None and trough_at_worst is not None else None)
    return {
        'peak': {'value': round(hi[1], 2), 'date': hi[0]},
        'trough': {'value': round(lo[1], 2), 'date': lo[0]},
        'current': {'value': round(cur, 2), 'date': cur_date},
        'current_dd_pct': cur_dd,           # retracement of today from running peak
        'max_dd_pct': round(worst, 2),
        'max_dd_abs': max_dd_abs,
        'max_dd_peak_date': worst_peak_date,
        'max_dd_trough_date': worst_trough_date,
        'at_low': abs(cur - lo[1]) < 1e-6,  # today == all-time low in window
    }


def _profit_extremes(series):
    """Like _series_extremes but for 总利润 (浮盈+已实现), which can go NEGATIVE.

    A % drawdown on a series that crosses zero is nonsense (peak +4.8k → trough
    −25.9k would read −637%), so this reports money only: all-time peak / trough,
    today's value, and today's shortfall from the running peak in absolute terms
    (`from_peak_abs`, ≤ 0). No percentages — the equity series owns the % axis.
    """
    pts = [(d, float(v)) for d, v in series if v is not None]
    if not pts:
        return None
    peak = pts[0][1]
    worst_abs = 0.0
    worst_trough_date = pts[0][0]
    worst_peak_date = pts[0][0]
    worst_peak_val = pts[0][1]      # running peak at the worst drawdown (for the % guard)
    worst_trough_val = pts[0][1]
    peak_date = pts[0][0]
    for d, v in pts:
        if v > peak:
            peak = v
            peak_date = d
        gap = v - peak
        if gap < worst_abs:
            worst_abs = gap
            worst_trough_date = d
            worst_peak_date = peak_date
            worst_peak_val = peak
            worst_trough_val = v
    hi = max(pts, key=lambda x: x[1])
    lo = min(pts, key=lambda x: x[1])
    cur_date, cur = pts[-1]
    # Trade-invariant % drawdown — ONLY meaningful while profit stays positive
    # across the span (a series that crosses zero gives nonsense %, see docstring).
    # current_dd_pct: today's give-back vs the running peak; max_dd_pct: deepest.
    cur_dd_pct = (round((cur - peak) / peak * 100, 2)
                  if peak > 0 and cur > 0 else None)
    max_dd_pct = (round(worst_abs / worst_peak_val * 100, 2)
                  if worst_peak_val > 0 and worst_trough_val > 0 else None)
    return {
        'peak': {'value': round(hi[1], 2), 'date': hi[0]},
        'trough': {'value': round(lo[1], 2), 'date': lo[0]},
        'current': {'value': round(cur, 2), 'date': cur_date},
        'from_peak_abs': round(cur - peak, 2),       # today's shortfall vs running peak (≤0)
        'current_dd_pct': cur_dd_pct,                # % give-back from running peak (None if profit ≤0)
        'max_dd_abs': round(worst_abs, 2),           # deepest peak→trough drop ($, ≤0)
        'max_dd_pct': max_dd_pct,                    # deepest drop as % of peak (None if profit crossed ≤0)
        'max_dd_peak_date': worst_peak_date,
        'max_dd_trough_date': worst_trough_date,
        'max_dd_peak_val': round(worst_peak_val, 2),     # profit at the peak that started the worst DD
        'max_dd_trough_val': round(worst_trough_val, 2), # profit at the deepest trough
        'at_low': abs(cur - lo[1]) < 1e-6,
    }


def compute_drawdown(snapshots, fx_rate=None, legs=None):
    """All-time peak / trough / max-drawdown per leg AND combined.

    Basis = equity (market value + cumulative realized) so selling a position
    doesn't masquerade as a drawdown. The combined series folds the base leg into
    the QUOTE leg's currency at the current fx_rate (the HKD peg barely moves, so
    a constant rate is fine) — note this is the opposite direction from the
    combined P&L cards, which is why both label their currency.

    Legacy keys kept for back-compat:
      `max_pct_30d_*` = worst peak-to-trough retracement over the window.
      `current_pct_*` = (today - 30d-ago) / 30d-ago * 100.
    New keys: one per leg, plus `combined` → see `_series_extremes`.
    """
    legs = _ledger_legs() if legs is None else legs
    base_leg, quote_leg = (legs[0], legs[1]) if len(legs) == 2 else (None, None)
    # The legacy suffixed keys were emitted quote-leg-first. Key order is the
    # published field order, so it is reproduced rather than tidied.
    legacy = list(reversed(legs))
    empty = {}
    for leg in legacy:
        empty[f'max_pct_30d_{leg.key}'] = None
    for leg in legacy:
        empty[f'current_pct_{leg.key}'] = None
    for leg in legs:
        empty[leg.key] = None
    empty['combined'] = None
    empty['profit'] = {leg.key: None for leg in legs}
    empty['profit']['combined'] = None
    empty['profit']['basis'] = 'total profit (unrealized + realized), money-only'
    empty['basis'] = 'equity (market value + realized)'
    try:
        if not snapshots:
            return empty
        n = len(snapshots)
        window = snapshots[-30:] if n >= 30 else snapshots[:]

        def max_drawdown_pct(key):
            peak = None
            worst = None
            for s in window:
                v = s.get(key)
                if v is None:
                    continue
                try:
                    v = float(v)
                except Exception:
                    continue
                if peak is None or v > peak:
                    peak = v
                if peak and peak > 0:
                    dd = (v - peak) / peak * 100
                    if worst is None or dd < worst:
                        worst = dd
            return round(worst, 2) if worst is not None else None

        # current vs 30d-ago using min(29, n-1) offset back from today
        offset = min(29, n - 1)
        base_idx = (n - 1) - offset
        today = snapshots[-1]
        base = snapshots[base_idx]

        def current_pct(key):
            t = today.get(key)
            b = base.get(key)
            if t is None or b is None:
                return None
            try:
                t = float(t); b = float(b)
            except Exception:
                return None
            if b == 0:
                return None
            return round((t - b) / abs(b) * 100, 2)

        # All-time extremes (over every embedded snapshot, not just the 30d window).
        def _combined(field):
            """Base leg converted into the quote leg's currency, then added."""
            if not base_leg or not (fx_rate and fx_rate > 0):
                return None
            rows = []
            for s in snapshots:
                b, q = (s.get(f'{base_leg.key}_{field}'),
                        s.get(f'{quote_leg.key}_{field}'))
                if b is None or q is None:
                    continue
                rows.append((s.get('date'), b * fx_rate + q))
            return rows

        def _label(ext, currency):
            if ext:
                ext['currency'] = currency
            return ext

        fx_key = (f'fx_{base_leg.currency.lower()}{quote_leg.currency.lower()}'
                  if base_leg else 'fx_rate')
        comb_series = _combined('equity')
        combined = _series_extremes(comb_series) if comb_series is not None else None
        if combined:
            combined['currency'] = quote_leg.currency
            combined[fx_key] = round(fx_rate, 4)

        ext_by_leg = {
            leg.key: _label(
                _series_extremes([(s.get('date'), s.get(f'{leg.key}_equity'))
                                  for s in snapshots]),
                leg.currency)
            for leg in legs
        }

        # 总利润 (浮盈+已实现) extremes — money-only, parallel to the equity block.
        # Lets the dashboard answer "利润峰值到过多少 / 现在离峰值差多少 $" without the
        # market-value-peak ≠ profit-peak confusion that equity invites.
        profit_by_leg = {
            leg.key: _label(
                _profit_extremes([(s.get('date'), s.get(f'{leg.key}_profit'))
                                  for s in snapshots]),
                leg.currency)
            for leg in legs
        }
        comb_p = _combined('profit')   # same base as the combined equity series
        combined_profit_ext = _profit_extremes(comb_p) if comb_p is not None else None
        if combined_profit_ext:
            combined_profit_ext['currency'] = quote_leg.currency
            combined_profit_ext[fx_key] = round(fx_rate, 4)

        out = {}
        for leg in legacy:
            out[f'max_pct_30d_{leg.key}'] = max_drawdown_pct(f'{leg.key}_equity')
        for leg in legacy:
            out[f'current_pct_{leg.key}'] = current_pct(f'{leg.key}_equity')
        for leg in legs:
            out[leg.key] = ext_by_leg[leg.key]
        out['combined'] = combined
        out['profit'] = dict(profit_by_leg)
        out['profit']['combined'] = combined_profit_ext
        out['profit']['basis'] = 'total profit (unrealized + realized), money-only'
        out['basis'] = 'equity (market value + realized)'
        return out
    except Exception as e:
        print(f'  warn: compute_drawdown failed: {e}', file=sys.stderr)
        return empty


# ───────────────────────────────────────────────────────────────────────────
# v2.1: broker-style analytics
# ───────────────────────────────────────────────────────────────────────────

# Compatibility view for older imports; config/instruments.json owns the set.
LEVERAGED_TICKERS = instrument_registry.leveraged_symbols()


def compute_sector_exposure(portfolio):
    """Group active holdings by sector, with % of region book."""
    legs = resolve_legs(portfolio)
    result = {leg.key: [] for leg in legs}
    try:
        for leg in legs:
            r_key = leg.key
            holdings = portfolio['portfolios'][leg.bucket].get('holdings', [])
            active = [h for h in holdings if h.get('shares', 0) > 0]
            total_value = sum(h.get('current_value', 0) or 0 for h in active)
            if total_value <= 0:
                continue
            by_sector = {}
            for h in active:
                meta = instrument_registry.get(h['ticker'])
                sec = meta['sector'] if meta else 'Other'
                bucket = by_sector.setdefault(sec, {'value': 0.0, 'tickers': []})
                bucket['value'] += (h.get('current_value') or 0)
                bucket['tickers'].append(h['ticker'])
            for sec, info in by_sector.items():
                result[r_key].append({
                    'sector': sec,
                    'value': round(info['value'], 2),
                    'pct': round(info['value'] / total_value * 100, 2),
                    'tickers': info['tickers'],
                })
            result[r_key].sort(key=lambda x: x['pct'], reverse=True)
    except Exception as e:
        print(f'  warn: compute_sector_exposure failed: {e}', file=sys.stderr)
    return result


def compute_lookthrough_exposure(portfolio):
    """Dashboard-safe wrapper around the canonical exposure computation."""
    try:
        return instrument_registry.compute_lookthrough_exposure(portfolio)
    except Exception as e:
        print(f'  warn: compute_lookthrough_exposure failed: {e}', file=sys.stderr)
        return {leg.key: {} for leg in resolve_legs(portfolio)}


def compute_reentry_radar(lev_regime, portfolio):
    """再入场雷达 — 把「持币等回 200MA 再布局」的隐性计划显式化。

    每个受监控标的距其均线(HK=HSTECH 指数 200MA;US=per-name underlying 200MA,
    新上市名用短均线)多少、右侧趋势是否 ON。触发 = trend_on 翻 True(收盘站回均线上方)。
    数据全复用 lev_regime,不新抓;弹药用 live 现金,绝不硬编码(现金会随成交漂移)。
    排序:已触发(可布局)排前,其余按距均线从近到远(越近越该盯)。"""
    if not lev_regime:
        return None
    watches = []
    hk = lev_regime.get('hk') or {}
    if hk.get('close') is not None and hk.get('ma') is not None:
        watches.append({
            'market': 'HK', 'name': 'HSTECH', 'etf': None, 'kind': 'index',
            'close': hk.get('close'), 'ma': hk.get('ma'),
            'ma_window': lev_regime.get('ma_window', 200),
            'dist_ma_pct': hk.get('dist_ma_pct'),
            'trend_on': bool(hk.get('trend_on')),
            'state': None, 'note': None,
        })
    for n in (lev_regime.get('us') or {}).get('names') or []:
        if n.get('close') is None or n.get('ma') is None:
            continue
        watches.append({
            'market': 'US', 'name': n.get('underlying') or n.get('etf'),
            'etf': n.get('etf'), 'kind': 'stock',
            'close': n.get('close'), 'ma': n.get('ma'),
            'ma_window': n.get('ma_window'),
            'dist_ma_pct': n.get('dist_ma_pct'),
            'trend_on': bool(n.get('trend_on')),
            'state': n.get('state'), 'note': n.get('note'),
        })
    if not watches:
        return None
    watches.sort(key=lambda w: (not w['trend_on'],
                                abs(w['dist_ma_pct']) if w['dist_ma_pct'] is not None else 999))
    us_pf, hk_pf = leg_books(portfolio)
    return {
        'watches': watches,
        'triggered_count': sum(1 for w in watches if w['trend_on']),
        'total': len(watches),
        'powder': {'us_cash_usd': us_pf.get('cash_usd'),
                   'hk_cash_hkd': hk_pf.get('cash_hkd')},
        'as_of': lev_regime.get('as_of'),
    }


def compute_leveraged_etf_exposure(portfolio, fx_rate):
    """Percent of book in 2x/3x leveraged ETFs, per region + combined (USD-base)."""
    out = {'us_pct': None, 'hk_pct': None, 'combined_pct': None, 'tickers': []}
    try:
        us_book, hk_book = leg_books(portfolio)
        us_active = [h for h in us_book.get('holdings', [])
                     if h.get('shares', 0) > 0]
        hk_active = [h for h in hk_book.get('holdings', [])
                     if h.get('shares', 0) > 0]

        us_total = sum(h.get('current_value', 0) or 0 for h in us_active)
        hk_total = sum(h.get('current_value', 0) or 0 for h in hk_active)
        us_lev   = sum(h.get('current_value', 0) or 0 for h in us_active if h['ticker'] in LEVERAGED_TICKERS)
        hk_lev   = sum(h.get('current_value', 0) or 0 for h in hk_active if h['ticker'] in LEVERAGED_TICKERS)

        if us_total > 0: out['us_pct'] = round(us_lev / us_total * 100, 2)
        if hk_total > 0: out['hk_pct'] = round(hk_lev / hk_total * 100, 2)

        if fx_rate and fx_rate > 0 and (us_total + hk_total) > 0:
            us_usd_total = us_total
            hk_usd_total = hk_total / fx_rate
            us_usd_lev   = us_lev
            hk_usd_lev   = hk_lev / fx_rate
            combined_total = us_usd_total + hk_usd_total
            combined_lev   = us_usd_lev   + hk_usd_lev
            if combined_total > 0:
                out['combined_pct'] = round(combined_lev / combined_total * 100, 2)

        out['tickers'] = sorted(set(
            h['ticker'] for h in us_active + hk_active if h['ticker'] in LEVERAGED_TICKERS
        ))
    except Exception as e:
        print(f'  warn: compute_leveraged_etf_exposure failed: {e}', file=sys.stderr)
    return out


def compute_current_holdings_extremes(portfolio, top_n=3):
    """Top-N winners + bottom-N losers across all active holdings (by pnl_percent)."""
    out = {'winners': [], 'losers': []}
    try:
        rows = []
        for leg in resolve_legs(portfolio):
            r_key = leg.key
            for h in portfolio['portfolios'][leg.bucket].get('holdings', []):
                if h.get('shares', 0) <= 0:
                    continue
                p = h.get('pnl_percent')
                if p is None:
                    continue
                rows.append({
                    'ticker':      h['ticker'],
                    'name':        h.get('stock_name') or h.get('name', h['ticker']),
                    'region':      r_key,
                    'pnl_percent': round(float(p), 2),
                    'pnl_abs':     h.get('pnl_abs'),
                    'current_value': h.get('current_value'),
                })
        rows.sort(key=lambda x: x['pnl_percent'], reverse=True)
        out['winners'] = rows[:top_n]
        out['losers']  = sorted(rows, key=lambda x: x['pnl_percent'])[:top_n]
    except Exception as e:
        print(f'  warn: compute_current_holdings_extremes failed: {e}', file=sys.stderr)
    return out


def compute_today_ranges(portfolio, top_n=8):
    """Today's high-low spread as % of current price, sorted desc."""
    rows = []
    try:
        for leg in resolve_legs(portfolio):
            r_key = leg.key
            for h in portfolio['portfolios'][leg.bucket].get('holdings', []):
                if h.get('shares', 0) <= 0:
                    continue
                hi = h.get('day_high'); lo = h.get('day_low'); cur = h.get('current_price')
                if hi is None or lo is None or cur is None or cur <= 0:
                    continue
                try:
                    hi = float(hi); lo = float(lo); cur = float(cur)
                except Exception:
                    continue
                if hi == lo:
                    continue
                rows.append({
                    'ticker':    h['ticker'],
                    'region':    r_key,
                    'high':      round(hi, 4),
                    'low':       round(lo, 4),
                    'current':   round(cur, 4),
                    'range_pct': round((hi - lo) / cur * 100, 2),
                })
    except Exception as e:
        print(f'  warn: compute_today_ranges failed: {e}', file=sys.stderr)
    rows.sort(key=lambda x: x['range_pct'], reverse=True)
    return rows[:top_n]


def compute_realized_vs_unrealized(portfolio, fx_rate):
    """Realized + unrealized split per leg + combined in the base leg's currency.

    `fx_rate` is quote-currency per unit of base currency, so the quote leg is
    divided by it. The combined figure exists only when both a rate and exactly
    two books do — see `leg_pair`.
    """
    legs = resolve_legs(portfolio)
    base, quote = leg_pair(portfolio)
    # `combined` without a suffix is the honest label when the ledger never said
    # what currency the sum would be in — and in that case it stays None.
    combined_key = f'combined_{base.currency.lower()}' if base else 'combined'
    out = {leg.key: {'realized': None, 'unrealized': None} for leg in legs}
    out[combined_key] = {'realized': None, 'unrealized': None}
    try:
        books = portfolio['portfolios']
        for leg in legs:
            book = books[leg.bucket]
            out[leg.key]['realized'] = (
                book.get('total_realized_pnl') or book.get('realized_pnl') or 0.0)
            out[leg.key]['unrealized'] = book.get('total_pnl') or 0.0
        if base and fx_rate and fx_rate > 0:
            out[combined_key]['realized'] = round(
                out[base.key]['realized'] + out[quote.key]['realized'] / fx_rate, 2)
            out[combined_key]['unrealized'] = round(
                out[base.key]['unrealized'] + out[quote.key]['unrealized'] / fx_rate, 2)
    except Exception as e:
        print(f'  warn: compute_realized_vs_unrealized failed: {e}', file=sys.stderr)
    return out


def compute_capital_deployed(portfolio, fx_rate):
    """资本基准（"自己曾经拥有过的钱"） per region + combined USD-eq.

    Formula (option C, 2026-05-22 决定):
      basis = current_cost_basis(active holdings) + cumulative realized_pnl

    Why C 而不是 Σbuys：Σbuys 会把 rotation churn 重复计算（同一笔钱在 07709
    海力士里反复买卖每次都计入）。C 是没有完整 cash-flow log 的个人 tracker
    最诚实的"capital basis"近似 —— 代表"现在场上的钱 + 历史已兑现拿出来的"。
    雪球非 TWR 模式逻辑类似。

    行业标准 TWR / MWR 需要每日 portfolio value + 时间戳现金流（含
    deposit/withdrawal），我们没有这个数据。

    See 2026-05-22 conversation with kcn (rotation churn 问题).
    """
    legs = resolve_legs(portfolio)
    base, quote = leg_pair(portfolio)
    base_ccy = base.currency.lower() if base else None
    combined_key = f'combined_{base_ccy}' if base_ccy else 'combined'
    # The per-leg conversion field is named for the base currency, because that
    # is what it converts TO — `usd` here only because the base book is USD.
    conv = base_ccy or 'base'
    out = {leg.key: {'native': None, conv: None} for leg in legs}
    out[combined_key] = None

    try:
        books = portfolio['portfolios']
        for leg in legs:
            book = books[leg.bucket]
            out[leg.key]['native'] = round(
                (book.get('total_cost', 0) or 0) + (book.get('realized_pnl', 0) or 0), 2)
        if base:
            out[base.key][conv] = out[base.key]['native']  # base leg is already base currency
            if fx_rate and fx_rate > 0:
                out[quote.key][conv] = round(out[quote.key]['native'] / fx_rate, 2)
                out[combined_key] = round(out[base.key][conv] + out[quote.key][conv], 2)
    except Exception as e:
        print(f'  warn: compute_capital_deployed failed: {e}', file=sys.stderr)
    return out


def compute_net_principal_return(portfolio, fx_rate):
    """复利口径："自有现金"的真实回报 per region + combined USD-eq.

    Formula (2026-05-29 决定，与 capital_deployed 的 option-C 并列、互补):
      净投入本金 net_principal = current_cost_basis(active) − cumulative realized_pnl
      总收益    total_profit  = unrealized_pnl + realized_pnl
      回报率    return_pct    = total_profit / net_principal × 100

    Why 这个口径：active trader 会把卖出回笼的现金（含已兑现利润）反复滚进
    新仓。`cost − realized` 还原的是"还压在场上的自有现金净额"——把赚到又滚
    回去的利润从分母里剔除，于是 return_pct 反映自有资金的复利增速（赢家立刻
    再投会把这个数顶得很高，这正是复利效应，不是错算）。

    与 capital_deployed(cost+realized) 的关系：那个用"我曾经拥有过的钱"做分母
    （保守、不会过 100% churn），这个用"我净掏的钱"做分母（激进、体现滚动复利）。
    两个并排给 kcn 看，一上一下夹住真实回报。See 2026-05-29 conversation.

    net_principal ≤ 0 ⇒ 已收回的现金 ≥ 投入，纯用利润在玩，return_pct 无意义置 None。

    true_principal override (2026-05-29)：若 region 配了 `true_principal`（从交易
    现金流账本反推的峰值净投入＝实际自掏现金），优先用它当分母——net_principal
    (cost−realized) 会被频繁 churn 把分母做小、return_pct 虚高（US 一度到 142%）。
    true_principal 是更诚实的"我实际投了多少"。net_principal 仍照算并保留在输出里
    供参考；combined 也跟随用各 region 实际分母（denom）。
    """
    legs = resolve_legs(portfolio)
    base, quote = leg_pair(portfolio)
    combined_key = f'combined_{base.currency.lower()}' if base else 'combined'
    out = {leg.key: {'net_principal': None, 'total_profit': None, 'return_pct': None}
           for leg in legs}
    out[combined_key] = {'net_principal': None, 'total_profit': None, 'return_pct': None}
    out['formula'] = ('回报率 = (浮动 + 已实现) ÷ 本金；本金优先用 true_principal'
                      '（峰值净投入），否则用 净投入本金=累计成本−已实现')

    def _region(pf):
        cost = pf.get('total_cost', 0) or 0
        real = pf.get('realized_pnl', 0) or 0
        unrl = pf.get('total_pnl', 0) or 0
        net_principal = round(cost - real, 2)
        total_profit = round(real + unrl, 2)
        true_p = pf.get('true_principal')
        denom = round(true_p, 2) if (true_p and true_p > 0) else net_principal
        ret = round(total_profit / denom * 100, 2) if denom and denom > 0 else None
        res = {
            'net_principal': net_principal,
            'total_profit':  total_profit,
            'return_pct':    ret,
            'return_basis':  'true_principal' if (true_p and true_p > 0) else 'net_principal',
            '_denom':        denom,
        }
        if true_p and true_p > 0:
            res['true_principal'] = round(true_p, 2)
            # 自洽跳闸：true_principal=峰值净投入，理应 ≥ 当前净投入(cost−realized)。
            # 若反超，说明加仓/补流水后常量没重算 → 警告（不阻断，回报率仍出）。
            if net_principal > true_p + 1:
                print(f'  warn: true_principal({true_p}) < net_principal({net_principal}) — 常量疑似过期，'
                      f'改持仓后请按现金流账本重算 true_principal', file=sys.stderr)
        return res

    try:
        books = portfolio['portfolios']
        for leg in legs:
            out[leg.key] = _region(books[leg.bucket])
        if base and fx_rate and fx_rate > 0:
            np_base = round(
                out[base.key]['_denom'] + out[quote.key]['_denom'] / fx_rate, 2)
            tp_base = round(
                out[base.key]['total_profit'] + out[quote.key]['total_profit'] / fx_rate, 2)
            # combined 分母是混合的：一条腿可能用 true_principal、另一条用 net_principal。
            # 暴露 basis 让前端标签诚实（任一腿用真实本金即标「真实本金」）。
            mixed_basis = ('true_principal'
                           if 'true_principal' in (out[base.key].get('return_basis'),
                                                   out[quote.key].get('return_basis'))
                           else 'net_principal')
            out[combined_key] = {
                'net_principal': np_base,
                'total_profit': tp_base,
                'return_pct': round(tp_base / np_base * 100, 2) if np_base > 0 else None,
                'return_basis': mixed_basis,
            }
        # _denom 仅用于 combined 计算，不外泄到输出
        for leg in legs:
            out[leg.key].pop('_denom', None)
    except Exception as e:
        print(f'  warn: compute_net_principal_return failed: {e}', file=sys.stderr)
    return out


# Freshness policy.  Runtime-written artifacts keep the historical max-age
# behavior.  GitHub weekday scans instead compare mtime with the latest cron
# fire that should have completed: a Friday artifact is valid all weekend, but
# becomes stale on Monday shortly after the next expected run.  Per-fire grace
# absorbs measured GitHub schedule delay plus commit serialization.
_MON_FRI = (0, 1, 2, 3, 4)           # datetime.weekday(): Monday == 0
_UTC_SUN_THU = (0, 1, 2, 3, 6)


def _scheduled_fire(weekdays, hour, minute, grace_hours, *, tz='UTC',
                    required_when=None):
    if not weekdays:
        raise ValueError('scheduled freshness fire needs at least one weekday')
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and grace_hours >= 0):
        raise ValueError('invalid scheduled freshness fire')
    return {
        'weekdays': tuple(sorted(weekdays)),
        'hour': hour,
        'minute': minute,
        'grace_hours': grace_hours,
        'timezone': tz,
        **({'required_when': required_when} if required_when else {}),
    }


def _scheduled_policy(sla_hours, *fires):
    if not fires:
        raise ValueError('scheduled freshness policy needs at least one fire')
    return {
        'sla_hours': sla_hours,
        'schedule': {'fires': tuple(fires)},
    }


_BRIEF_FRESHNESS_ARTIFACTS = frozenset({
    'quant_signals.json',
    'quant_signal_review.json',
    'cross_sectional_factor.json',
    'peer_residual.json',
    'news_evidence_graph.json',
    'risk.json',
    'lev_regime.json',
    'catalysts.json',
    'em_news.json',
})

# The local brief normally commits in minutes but has a remote fallback and a
# 10:00 HKT landing window.  Do not declare it missed until 14:00 HKT.  Unlike
# GitHub scans, the brief intentionally skips a fire when both covered markets
# are closed, so its descriptor mirrors that producer gate.
_BRIEF_FIRE = _scheduled_fire(
    _MON_FRI, 8, 0, 6, tz='Asia/Shanghai', required_when='any_market_open'
)


_FRESHNESS_POLICY = {
    'portfolio.json': {'sla_hours': 26},
    **{
        name: _scheduled_policy(30, _BRIEF_FIRE)
        for name in _BRIEF_FRESHNESS_ARTIFACTS
    },
    'benchmark.json': {'sla_hours': 80},  # 偶发限流，宽容
    # Grace is per fire, rounded above producer-only history (max observed:
    # macro 4.32h, sentiment 4.60h, influencer 5.04h, digest 5.57h).
    'macro.json': _scheduled_policy(
        30, _scheduled_fire(_UTC_SUN_THU, 21, 45, 5)
    ),
    'sentiment.json': _scheduled_policy(
        30, _scheduled_fire(_UTC_SUN_THU, 21, 30, 6)
    ),
    'us_news_digest.json': _scheduled_policy(
        30, _scheduled_fire(_MON_FRI, 13, 0, 7)
    ),
    'influencer_feed.json': _scheduled_policy(
        30,
        _scheduled_fire(_UTC_SUN_THU, 21, 40, 6),
        _scheduled_fire(_MON_FRI, 12, 50, 6),
    ),
}

# Compatibility/readability alias for callers that only need the max-age
# metadata.  `_FRESHNESS_POLICY` is the single source of truth.
_FRESHNESS_SLA_H = {
    name: policy['sla_hours'] for name, policy in _FRESHNESS_POLICY.items()
}


def _fire_is_expected(fire, candidate, calendar):
    """Mirror producer-side skip rules; unavailable calendars fail closed."""
    if fire.get('required_when') != 'any_market_open' or calendar is None:
        return True
    return any(
        calendar.closed_reason(
            market,
            candidate.astimezone(ZoneInfo(calendar.MARKET_TZ[market])).date(),
        ) is None
        for market in ('hk', 'us')
    )


def _latest_due_fire(schedule, at, calendar=None):
    """Latest fire whose own grace deadline has elapsed, normalized to UTC."""
    if at.tzinfo is None:
        raise ValueError('freshness reference time must be timezone-aware')
    latest = None
    for fire in schedule['fires']:
        fire_tz = ZoneInfo(fire['timezone'])
        cutoff = at.astimezone(fire_tz) - timedelta(hours=fire['grace_hours'])
        for days_back in range(8):
            candidate_date = cutoff.date() - timedelta(days=days_back)
            if candidate_date.weekday() not in fire['weekdays']:
                continue
            candidate = datetime(
                candidate_date.year,
                candidate_date.month,
                candidate_date.day,
                fire['hour'],
                fire['minute'],
                tzinfo=fire_tz,
            )
            if candidate > cutoff or not _fire_is_expected(
                fire, candidate, calendar
            ):
                continue
            scheduled_at = candidate.astimezone(timezone.utc)
            due = {
                'scheduled_at': scheduled_at,
                'deadline_at': scheduled_at + timedelta(
                    hours=fire['grace_hours']
                ),
                'grace_hours': fire['grace_hours'],
            }
            if latest is None or scheduled_at > latest['scheduled_at']:
                latest = due
            break
    return latest


def _latest_completed_session(market, calendar, at=None):
    """Newest trading session that has conservatively finished in market time.

    Thin now: the rule lives on the calendar, which is the only module that
    knows when a market is open. `calendar` stays a parameter because callers
    inject it, and it is still what answers the question.
    """
    return calendar.latest_completed_session(market, at)


def _quote_session(holding, reference):
    """Extract the holding's own quote date, never a shared file/region timestamp."""
    values = [
        holding.get('quote_time'),
        holding.get('as_of'),
        holding.get('last_updated'),
        holding.get('data_source'),
    ]
    parsed = []
    for raw in values:
        if not raw:
            continue
        text = str(raw)
        match = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', text)
        if match:
            try:
                parsed.append(date(*(int(part) for part in match.groups())))
            except ValueError:
                pass
            continue
        match = re.search(
            r'\b([A-Za-z]{3,9})\s+(\d{1,2})(?:,\s*|\s+)?(\d{4})?\b',
            text,
        )
        if not match or reference is None:
            continue
        month, day, year = match.groups()
        try:
            candidate = datetime.strptime(
                f'{month} {day} {year or reference.year}', '%b %d %Y'
            ).date()
        except ValueError:
            try:
                candidate = datetime.strptime(
                    f'{month} {day} {year or reference.year}', '%B %d %Y'
                ).date()
            except ValueError:
                continue
        # A yearless Dec quote inspected in early Jan belongs to the prior year.
        if year is None and candidate > reference + timedelta(days=7):
            candidate = candidate.replace(year=candidate.year - 1)
        parsed.append(candidate)
    return max(parsed) if parsed else None


def _market_leg_freshness(portfolio_leg, market, calendar, at=None):
    expected = _latest_completed_session(market, calendar, at=at)
    active = [
        holding for holding in portfolio_leg.get('holdings', [])
        if (holding.get('shares') or 0) > 0
    ]
    quotes = {}
    missing = []
    stale = []
    for holding in active:
        ticker = holding.get('ticker') or holding.get('code') or '?'
        session = _quote_session(holding, expected)
        quotes[ticker] = session.isoformat() if session else None
        if session is None:
            missing.append(ticker)
        elif expected and session < expected:
            stale.append(ticker)
    dated = [value for value in quotes.values() if value]
    fresh = expected is not None and not missing and not stale
    return {
        'last_updated': portfolio_leg.get('last_updated'),
        'expected_completed_session': expected.isoformat() if expected else None,
        'oldest_quote_session': min(dated) if dated else None,
        'newest_quote_session': max(dated) if dated else None,
        'active_holdings': len(active),
        'missing_quote_timestamps': sorted(missing),
        'stale_tickers': sorted(stale),
        'quote_sessions': quotes,
        'fresh': fresh,
    }


def compute_build_status(portfolio, data_dir, at=None):
    """A2 健康卡数据：每个数据文件的新鲜度 + 体检结论 + 每市场 data 时点。

    纯文件运算、零网络。被动暴露 staleness 给前端（不推送，遵 feedback_no_individual_cron_alerts）。
    内联跑一次 `clawock integrity` 取新鲜体检结论嵌进来。
    """
    now = at if at is not None else datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    try:
        from clawock import sessions as _tc
    except Exception:
        _tc = None
    files = []
    targets = ['portfolio.json'] + sorted(_FRESHNESS_POLICY.keys() - {'portfolio.json'})
    for name in targets:
        path = (WS_ROOT / name) if name == 'portfolio.json' else (data_dir / name)
        policy = _FRESHNESS_POLICY.get(name, {'sla_hours': 30})
        sla = policy['sla_hours']
        schedule = policy.get('schedule')
        due = _latest_due_fire(schedule, now, _tc) if schedule else None
        freshness_mode = 'scheduled_fire' if schedule else 'max_age'
        if path.exists():
            mtime = path.stat().st_mtime
            age_h = (now.timestamp() - mtime) / 3600.0
            stale = (
                mtime < due['scheduled_at'].timestamp()
                if due else age_h > sla
            )
            files.append({'name': name, 'age_hours': round(age_h, 1),
                          'sla_hours': sla, 'stale': stale, 'present': True,
                          'freshness_mode': freshness_mode,
                          **({'latest_due_at': due['scheduled_at'].isoformat(),
                              'deadline_at': due['deadline_at'].isoformat(),
                              'grace_hours': due['grace_hours']}
                             if due else {})})
        else:
            files.append({'name': name, 'present': False, 'stale': True,
                          'sla_hours': sla, 'freshness_mode': freshness_mode,
                          **({'latest_due_at': (
                                  due['scheduled_at'].isoformat() if due else None
                              ),
                              'deadline_at': (
                                  due['deadline_at'].isoformat() if due else None
                              ),
                              'grace_hours': (
                                  due['grace_hours'] if due else None
                              )}
                             if schedule else {})})

    # 每市场数据时点：逐只活跃持仓的报价日期 vs 最近已完成 session。
    # 不能信 region.last_updated 或 portfolio.json mtime；两者都会被另一条写入刷新。
    markets = {}
    for region, mkt in (('us_stocks', 'us'), ('hk_stocks', 'hk')):
        pf = portfolio.get('portfolios', {}).get(region, {})
        if _tc:
            markets[mkt] = _market_leg_freshness(pf, mkt, _tc, at=now)
            market_date = now.astimezone(ZoneInfo(_tc.MARKET_TZ[mkt])).date()
            markets[mkt]['closed_today'] = (
                _tc.closed_reason(mkt, market_date) is not None
            )
        else:
            markets[mkt] = {
                'last_updated': pf.get('last_updated'),
                'fresh': False,
                'error': 'trading_calendar unavailable',
            }

    # 体检结论（A1）——纯文件运算，安全内联
    integrity = None
    try:
        from clawock.portfolio import integrity as _pi
        rep = _pi.check()
        integrity = {'ok': rep['ok'], 'error_count': rep['error_count'],
                     'warn_count': rep['warn_count'],
                     'top': [{'code': f['code'], 'level': f['level'], 'msg': f['msg']}
                             for f in rep['findings']][:6]}
    except Exception as e:
        print(f'  warn: integrity check in build_status failed: {e}', file=sys.stderr)

    stale_files = [f['name'] for f in files if f.get('stale')]
    stale_markets = [market for market, state in markets.items()
                     if not state.get('fresh')]
    healthy = (not stale_files) and (not stale_markets) and (
        integrity is None or integrity.get('ok'))
    return {'generated_at': now.isoformat(timespec='seconds'), 'healthy': healthy,
            'stale_files': stale_files, 'stale_markets': stale_markets,
            'files': files, 'markets': markets,
            'integrity': integrity}


def compute_workflow_outcomes():
    """Read and summarize the package-produced outcome sidecar.

    The dashboard projection treats the ledger like any other optional
    workspace input; generated state remains outside the wheel even though its
    lifecycle implementation belongs to the package.
    """
    try:
        payload = load_json(WS_ROOT / 'assets' / 'data' / 'workflow-outcomes.json')
        # The published file is the ledger itself — `{records: [...]}` — because
        # the adapter reads it back as its own fresh-checkout recovery source.
        # The card wants the window fold of it, so do the fold here rather than
        # trimming raw records into a payload with no `counts` and no `recent`.
        summary = trim_workflow_outcomes(dashboard_outcomes.summarize_records(
            (payload or {}).get('records', [])))
        # The chain's own faults ride with the counts they call into question
        # (#1214). Five fail-open handlers used to report onto stderr, which
        # reaches no gate — so a reconcile that never ran and a reconcile with
        # nothing to do produced the identical card. `degradations` is normally
        # absent; when it is not, every number beside it was computed by a
        # bookkeeping pass that knows it degraded.
        degradations = dashboard_outcomes.degradations_of(payload)
        if degradations and isinstance(summary, dict):
            summary['degradations'] = degradations
        return summary
    except Exception as e:
        print(f'  warn: workflow outcome summary failed: {e}', file=sys.stderr)
        return None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Build the public dashboard payloads from the workspace.')
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        '--previous', metavar='PATH', default=None,
        help='dashboard payload to restore card values from when their source '
             'context is absent from this checkout. Opt-in: a build that is '
             'going to be published from a checkout without the memory/.tmp '
             f'sidecars passes the published {OUT_FILE.name} here')
    source.add_argument(
        '--no-previous', action='store_true',
        help='build from the workspace alone; no output may come from a '
             'previously published file. This is the default — pass it to state '
             'the guarantee explicitly')
    parser.add_argument(
        '--out-dir', metavar='DIR', default=None,
        help='write the four outputs of this generation into DIR instead of the '
             'published location. Beats the BUILD_DASHBOARD_OUT / '
             'DECISION_AUDIT_OUT / SHADOW_PORTFOLIO_OUT redirects')
    parser.add_argument(
        '--skip-if-unchanged', action='store_true',
        help='hash the projection inputs first and skip the whole build when '
             'they match the last build\'s fingerprint (stored under '
             '.cache/dashboard-input.json). The 20-minute publisher uses this '
             'so an unchanged desk does not reparse ~12MB of JSON every tick '
             '(#846).')
    return parser.parse_args(argv)


def resolve_output_paths(out_dir=None):
    """The four files one generation lands in, keyed by payload name.

    Precedence: an explicit `--out-dir` beats the per-file environment redirects,
    which beat the published locations. Explicit beats ambient — a caller that
    named a directory should not have an inherited env var silently move one of
    the four files out of it and split the generation across two places.

    The env vars stay because they are what system_check's buildability gate and
    the Actions validation jobs already use. `--out-dir` is the form a caller
    outside this repository wants, and is what makes a projection buildable
    anywhere (#262 slice 3 step 4).

    Note the old `OVERVIEW_FILE if out_file == OUT_FILE else …` conditional is
    gone: `OVERVIEW_FILE` is `OUT_FILE.parent / 'overview.json'`, so both arms
    always produced the same path.
    """
    if out_dir:
        directory = Path(out_dir)
        return {
            'overview': directory / OVERVIEW_FILE.name,
            'dashboard': directory / OUT_FILE.name,
            'audit': directory / AUDIT_FILE.name,
            'shadow': directory / 'shadow_portfolio.json',
        }
    out_file = Path(os.environ.get('BUILD_DASHBOARD_OUT') or OUT_FILE)
    return {
        'overview': out_file.parent / OVERVIEW_FILE.name,
        'dashboard': out_file,
        'audit': Path(os.environ.get('DECISION_AUDIT_OUT')
                      or (out_file.parent / AUDIT_FILE.name)),
        'shadow': Path(os.environ.get('SHADOW_PORTFOLIO_OUT')
                       or (out_file.parent / 'shadow_portfolio.json')),
    }


def resolve_previous_source(args):
    """The payload file this build may restore absent cards from, or None.

    Workspace-only is the DEFAULT (#262 slice 2). Reading the last published
    dashboard makes the output depend on this repository's own history, so the
    builder does not do it unless a caller names the file. The callers that
    still want it are the ones that publish from a checkout which may lack the
    memory/.tmp sidecars — `publish_dashboard.sh`, `rebuild_dashboard()` (which
    covers all three postflights, and through them `brief-fallback.yml`) and the
    pre-commit hook. Every other caller either has the sidecars or never
    publishes, and gets the workspace-only build.

    Inverting this is the point of the slice: before, a silent default meant a
    fresh checkout could publish yesterday's cards without anyone asking it to.
    """
    if args.no_previous:
        return None
    return Path(args.previous) if args.previous else None


# ---------------------------------------------------------------------------
# Input fingerprint (#846): the cheap gate that lets the 20-minute publisher
# skip a build whose inputs did not move. mtime is read at ns resolution so a
# same-second rewrite still moves the fingerprint, with size as the second key.
#
# What this comment used to claim, and why it was wrong (#1217)
# -------------------------------------------------------------
# It said "everything the projection reads is stat-level covered: five named
# files, four directories and the daily plan glob". It was not. The projection
# embeds most of the data plane — sentiment, macro, the news digest, the
# influencer feed, the quant signals, the leverage dial, the workflow ledger —
# and of all of those exactly one, `risk.json`, was in the tuple. Demonstrated
# by `test_dashboard_fingerprint.py`: rewriting sentiment, macro, lev_regime and
# workflow-outcomes left the fingerprint byte-identical, so the 72x/day
# publisher would skip the rebuild and keep serving the previous embed until
# some *unrelated* input — a bar, a snapshot, portfolio.json — happened to move.
# The desk changes often enough that this was masked most of the day. It is
# exactly overnight and at the weekend, when a scheduled scan is the only thing
# writing, that it was not.
#
# The data-plane half is now derived from `_FRESHNESS_POLICY` rather than typed
# out again. That table already has to list every artifact whose staleness the
# page reports, so a new embed cannot enter the build without entering the
# fingerprint — the drift that produced this bug cannot repeat silently, and
# `test_fingerprint_covers_every_data_plane_file_the_build_reads` runs a real
# build under an instrumented reader to assert the same thing behaviourally.
#
# The build's own outputs are deliberately absent: fingerprinting them would
# mean every build invalidated the next tick's gate. So are the artifacts some
# *other* publisher rewrites on every tick (`cron-heartbeats.json`), which the
# projection does not read and which would defeat the gate for nothing.
# ---------------------------------------------------------------------------

# Read by the builder but not freshness-policed, so they need naming here.
_FINGERPRINT_EXTRA_DATA_PLANE = (
    'workflow-outcomes.json',
    't0_setups.json',
    't0_setup_review.json',
    # Read by `annotate_guardrail_history`. `brief_preflight` appends to it in
    # the same run that then rebuilds the dashboard, so a fingerprint that
    # could not see it would let --skip-if-unchanged publish yesterday's trend.
    GUARDRAIL_HISTORY_NAME,
)

FINGERPRINT_FILES = (
    'portfolio.json',
    'memory/decisions.jsonl',
    'memory/fx-rates.jsonl',
    '.cache/fx_rate.json',
) + tuple(sorted(
    f'assets/data/{name}'
    for name in set(_FRESHNESS_POLICY) | set(_FINGERPRINT_EXTRA_DATA_PLANE)
    # portfolio.json is freshness-policed and lives at the workspace root, not
    # in the data plane; it is named above.
    if name != 'portfolio.json'
))
FINGERPRINT_DIRS = ('memory/bars', 'memory/snapshots', 'memory/weekly', 'memory/.tmp')
FINGERPRINT_CACHE = '.cache/dashboard-input.json'
# Names under FINGERPRINT_DIRS that THIS build writes, so they describe the
# build rather than feed it. `record_preservation` appends a line to
# memory/.tmp/preserve-absent-YYYY-MM-DD.jsonl on every build, which is inside
# the fingerprinted `memory/.tmp` — so each build moved the fingerprint its
# successor's gate reads, and `--skip-if-unchanged` could never fire once,
# anywhere (#1247). Same shape as the snapshot writer #1217 fixed; this was the
# second self-writer and it survived because the gate fails silently: it does
# not error, it just always rebuilds.
#
# Deliberately a prefix tuple and not "drop memory/.tmp": the other sidecars in
# there — brief-context, insights, intraday-insights, sector-scan — are real
# inputs the projection embeds, and dropping the whole directory would trade
# this stall for the #1217 staleness bug in a card nobody watches.
FINGERPRINT_SELF_WRITTEN = (PRESERVE_ABSENT_PREFIX,)


def dashboard_input_fingerprint(ws: Path) -> str:
    h = hashlib.sha1()
    for rel in FINGERPRINT_FILES:
        p = ws / rel
        try:
            st = p.stat()
            h.update(f'{rel}:{st.st_mtime_ns}:{st.st_size}\n'.encode())
        except OSError:
            h.update(f'{rel}:missing\n'.encode())
    for rel in FINGERPRINT_DIRS:
        d = ws / rel
        try:
            names = sorted(os.listdir(d))
        except OSError:
            names = []
        # Filtered before the count, or a new day's telemetry file would move
        # the fingerprint through `count=` even with its stat line excluded.
        names = [n for n in names if not n.startswith(FINGERPRINT_SELF_WRITTEN)]
        h.update(f'{rel}:count={len(names)}\n'.encode())
        for name in names:
            try:
                st = (d / name).stat()
                h.update(f'{rel}/{name}:{st.st_mtime_ns}:{st.st_size}\n'.encode())
            except OSError:
                pass
    try:
        plans = sorted(glob.glob(str(ws / 'memory' / '*-plan.json')))
    except OSError:
        plans = []
    h.update(f'plans:count={len(plans)}\n'.encode())
    for p in plans:
        try:
            st = os.stat(p)
            h.update(f'plan:{os.path.basename(p)}:{st.st_mtime_ns}:{st.st_size}\n'.encode())
        except OSError:
            pass
    return h.hexdigest()


def _read_fingerprint_cache(ws: Path) -> str | None:
    try:
        return json.loads((ws / FINGERPRINT_CACHE).read_text()).get('fingerprint')
    except Exception:
        return None


def _write_fingerprint_cache(ws: Path, fingerprint: str) -> None:
    cache = ws / FINGERPRINT_CACHE
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix('.tmp')
    tmp.write_text(json.dumps({'fingerprint': fingerprint}) + '\n')
    tmp.replace(cache)


class ProjectionInputError(Exception):
    """The workspace cannot produce a projection. Reported, never published."""


class MissingPortfolio(ProjectionInputError):
    """portfolio.json is the one input a projection cannot be built without."""


class UnsupportedLegShape(ProjectionInputError):
    """The ledger does not have the two-book shape the cards are defined for.

    Deliberately fatal rather than "publish the two books we recognise": every
    combined figure would then quietly omit a book, and a total that silently
    drops money is worse than a dashboard that stops updating and says why.
    """


def build_projection(previous_source=None, shadow_previous=None):
    """Compute the four public payloads from the workspace. Writes nothing.

    Returns `{dashboard, overview, audit, shadow, preservation, summary}` — the
    complete generation, in memory. Which files those payloads end up in, and
    whether they are written at all, is `main()`'s business (#262 slice 3).

    Separating this out is what makes the projection testable against a
    synthetic workspace, and it is the precondition for the later slices: a
    renderer can only consume a projection directory if a projection is a value
    rather than a side effect of writing four files.

    `previous_source` is the opt-in payload from slice 2 — a path, read here, and
    named in `dashboard.build_status.previous_payload`. `shadow_previous` is the
    shadow sidecar as it stands on disk, needed only to keep the last successful
    `as_of` as provenance when the simulation fails; the caller reads it because
    the caller is the one that knows where the sidecar lives.

    Raises `MissingPortfolio` when the ledger is absent. Everything else degrades
    into the payload — a build that cannot compute a card publishes the card's
    failure, it does not abort the generation.
    """
    portfolio = load_json(WS_ROOT / 'portfolio.json')
    if not portfolio:
        raise MissingPortfolio(str(WS_ROOT / 'portfolio.json'))

    # The two books, named by the ledger rather than by this file. `us_h`/`hk_h`
    # keep their names because 40-odd call sites downstream still read them; what
    # changes here is that nothing hardcodes which bucket they came from.
    base_leg, quote_leg = leg_pair(portfolio)
    if not base_leg:
        raise UnsupportedLegShape(
            'portfolio.json must declare exactly two books, each with a '
            'currency; found '
            + repr([(leg.bucket, leg.currency) for leg in resolve_legs(portfolio)]))
    us_pf = portfolio['portfolios'][base_leg.bucket]
    hk_pf = portfolio['portfolios'][quote_leg.bucket]

    us_h = [trim_holding(h, base_leg.currency) for h in us_pf.get('holdings', [])]
    hk_h = [trim_holding(h, quote_leg.currency) for h in hk_pf.get('holdings', [])]

    us_conc = compute_hhi(us_h)
    hk_conc = compute_hhi(hk_h)
    us_conc['verdict'] = hhi_verdict(us_conc['hhi'], us_conc['top2'])
    hk_conc['verdict'] = hhi_verdict(hk_conc['hhi'], hk_conc['top2'])

    fx_cache = load_json(WS_ROOT / '.cache' / 'fx_rate.json') or {}

    snapshots = load_snapshots()
    plans = load_plans()

    out = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        'last_updated': portfolio.get('last_updated', ''),
        'fx': {
            'usdhkd': fx_cache.get('rate'),
            'source': fx_cache.get('source'),
            'fetched_at': fx_cache.get('fetched_at'),
        },
        'totals': {leg.key: leg_totals(leg, book)
                   for leg, book in ((base_leg, us_pf), (quote_leg, hk_pf))},
        'concentration': {base_leg.key: us_conc, quote_leg.key: hk_conc},
        'holdings': {
            # Only ship live positions to the client — shares=0 (fully-exited) names keep
            # their trades[] in portfolio.json for realized-P&L, but the frontend never
            # renders them (every consumer filters is_active), so excluding them here just
            # trims dashboard.json. Intermediate us_h/hk_h above stay full for compute_hhi.
            base_leg.key: [h for h in us_h if (h.get('shares') or 0) > 0],
            quote_leg.key: [h for h in hk_h if (h.get('shares') or 0) > 0],
        },
        'snapshots': snapshots,
        'snapshots_total': total_snapshots_count(),
        'snapshots_embedded_cap': MAX_SNAPSHOTS_EMBEDDED,
        'plans_count': total_plans_count(),
        'recent_plans': plans,
        'recent_plans_cap': MAX_PLANS_EMBEDDED,
        'indices': _aggregate_indices(us_pf, hk_pf),
        'market_context': load_sector_scan() or portfolio.get('market_context', {}),
        'holdings_history': build_holdings_history(
            sorted(
                p for p in glob.glob(str(WS_ROOT / 'memory' / 'snapshots' / '*.json'))
                if SNAPSHOT_FNAME_RE.match(os.path.basename(p))
            ),
            days=8,
        ),
    }

    # ── Dashboard v2 NEW fields (additive; never replace existing keys) ─
    brief_ctx_path, brief_ctx = _latest_brief_context()
    out['delta'] = compute_delta(snapshots)
    out['today_movers'] = compute_today_movers(
        us_h, hk_h, leg_keys=(base_leg.key, quote_leg.key))

    # merge-not-overwrite guard for sidecar-derived cards. A context-less rebuild
    # (fresh checkout: memory/.tmp is gitignored, so brief-context + insights/
    # intraday sidecars are ABSENT — meaning "not in THIS checkout", NOT "no insight
    # today") must NOT blank the cards the last local build published, or Pages
    # flickers empty. Restore the last non-empty published value whenever the
    # source context is absent. This regressed to anomalies-only at some point;
    # restored to all sidecar fields 2026-06-21 — see memory:
    # openclaw-gha-sidecar-strip-and-prepush-seterr.
    #
    # This is the one part of the output that does not come from the workspace,
    # so the file it comes from is an opt-in argument (`--previous`, default off
    # since #262 slice 2) and the keys it supplied are reported in build_status.
    # `_prev_dash` is `{}` for every caller that did not ask, which is what makes
    # a workspace the complete input to a build. Restoration is NOT
    # dead code: brief-fallback.yml publishes a dashboard rebuilt on an Actions
    # checkout that has a brief-context but no insights / intraday / sector-scan
    # sidecars, which is exactly the case this restores. See record_preservation.
    _prev_dash, _previous_missing = load_previous_payload(previous_source)
    _prev_dash = _prev_dash or {}
    _presence = {}

    out['anomalies'] = extract_anomalies(
        brief_ctx, us_h, hk_h, leg_keys=[leg.key for leg in resolve_legs(portfolio)])
    _presence['anomalies'] = bool(brief_ctx)

    # market_context is sector-scan-derived (load_sector_scan reads memory/.tmp,
    # absent on a fresh checkout) and portfolio.market_context is usually empty —
    # so a context-less rebuild would blank the 大盘速读 card. Preserve last good,
    # same merge-not-overwrite contract as the sidecar fields above. Its presence
    # test is the computed value itself rather than a source flag, because both
    # of its sources are optional.
    _presence['market_context'] = bool(out.get('market_context'))
    # #325 moved workflow-outcomes.json to the data branch, so a fresh-checkout
    # build (brief-fallback, which does not run workflow_outcomes.py) finds no
    # file at all. Without a presence entry the card would publish empty and
    # `--previous` could not restore it — the 2026-06-21 shape. The recovery
    # mechanism exists for exactly this; it just never covered this key.
    # Computed HERE, next to its presence test, and not 200 lines further down
    # where it used to be: `merge_previous_payload` runs in between, so the
    # restored card was overwritten by the empty computed one on exactly the
    # fresh-checkout build this entry exists to protect. The payload still said
    # `preserved: ['workflow_outcomes']`, which made the telemetry that decides
    # whether the merge can be retired report a recovery that never happened.
    out['workflow_outcomes'] = compute_workflow_outcomes()
    _presence['workflow_outcomes'] = bool(
        (out.get('workflow_outcomes') or {}).get('recent'))

    # ── LLM narrative sidecars (agent-written in Step 3; text-only, no keys) ──
    # Each sidecar is validated (validate_insights / validate_intraday_insights)
    # before it reaches dashboard.json: malformed / hallucinated content is dropped
    # so the card hides instead of publishing bad data. Anti-hallucination cross-check
    # is against the live book's tickers.
    known_tickers = {h.get('ticker') for h in (us_h + hk_h) if h.get('ticker')}
    # daily insights (brief): behavioral_review / bear_cases / hidden_concentration.
    # 7d stale guard so a missed brief doesn't show week-old critique as current.
    _insights = load_tmp_sidecar('insights', max_age_days=7)
    # True when the file existed at all — including when it existed but was
    # unreadable. Only genuine absence (a GHA checkout, where memory/.tmp is
    # gitignored) may republish the previous card; an unreadable file must let
    # the card hide rather than show yesterday's critique as today's.
    insights_present = bool(_insights)
    _ins = validate_insights({} if _insights.get('_stale') else _insights, known_tickers)
    out['behavioral_review'] = _ins['behavioral_review']
    out['bear_cases'] = _ins['bear_cases']
    out['hidden_concentration'] = _ins['hidden_concentration']
    out['insights_meta'] = {
        'source': _insights.get('_source'),
        'stale': _insights.get('_stale', True if not _insights else False),
    }
    for _k in ('behavioral_review', 'bear_cases', 'hidden_concentration', 'insights_meta'):
        _presence[_k] = insights_present
    # intraday insights (every 30min): status_banner + per-mover attribution.
    _intra = load_tmp_sidecar('intraday-insights', max_age_days=1)
    intra_present = bool(_intra)  # file existed in this checkout (vs. GHA-absent)
    _intra_v = validate_intraday_insights({} if _intra.get('_stale') else _intra, known_tickers)
    out['status_banner'] = _intra_v['status_banner']
    out['status_banner_meta'] = {
        'source': _intra.get('_source'),
        'generated_at': _intra.get('generated_at'),
        'stale': _intra.get('_stale', True if not _intra else False),
    }
    _presence['status_banner'] = intra_present
    _presence['status_banner_meta'] = intra_present

    # Merge validated mover attribution onto the deterministic movers list (by ticker).
    for _m in out['today_movers']:
        _note = _intra_v['movers'].get(_m.get('ticker'))
        if _note:
            _m['note'] = _note
    out['peer_divergence'] = {
        'as_of': (brief_ctx or {}).get('date')
                 or ((brief_ctx or {}).get('generated_at') or '')[:10],
        'items': extract_peer_divergence(brief_ctx, us_h, hk_h),
    }
    # peer_divergence is brief-context-derived → preserve last good when absent.
    # Its wrapper dict is truthy even with an empty items list, so restoring it
    # needs a stricter test than the other cards — hence `usable` below.
    _presence['peer_divergence'] = bool(brief_ctx) or bool(out['peer_divergence']['items'])

    # One merge, after every card above has been computed: the nine keys are
    # disjoint from everything read in between, so applying them together changes
    # nothing except that the set of restored keys can now be named. Anything
    # added later that falls back to `_prev_dash` belongs in this map, or the
    # payload will under-report what it copied.
    _preserved = merge_previous_payload(
        out, _prev_dash, _presence,
        usable={'peer_divergence': lambda v: isinstance(v, dict) and bool(v.get('items'))})
    # Decision system v2 is the only live scoring path. No CSV/signal-row
    # compatibility keys are emitted: frontend, README and harness share this.
    _decisions = decision_v2.load_decisions()
    decision_v2.settle_decisions(_decisions)
    # Reflect reads timing_diagnostic plus its episode backtest from this sidecar.
    # The full per-decision `records` trail (~700KB, recomputable from decisions)
    # is not rendered or linked anywhere, so it stays unpublished.
    _audit = build_decision_audit_payload(_decisions, portfolio)
    # Shadow-portfolio policy simulation (模拟·非实盘): its own sidecar, NOT embedded
    # in dashboard.json. Two cash+inventory ledgers (follow-all-triggered vs
    # same-seed buy-and-hold) marked to canonical closes; cumulative diff is a
    # simulated timing alpha, never live/broker performance.
    _shadow = build_shadow_sidecar(portfolio, _decisions, shadow_previous)
    out['decision_schema_version'] = 2
    out['decision_metrics'] = trim_decision_metrics(
        decision_v2.compute_metrics(_decisions))
    # decision_money_impact is deliberately NOT published (2026-07-15). Pulling the
    # chart while still shipping the numbers would be a distinction only a reader of
    # this file could make: dashboard.json is public, so the retired figure was still
    # one fetch away, still carrying "positive = following the AI beat not acting".
    # It summed calls that were never executed, priced against a drifting mark. The
    # function stays for the rebuild (see the official-bars task) — the field goes.
    out['decision_delta'] = decision_v2.decision_delta(_decisions)
    out['recent_decisions'] = decision_v2.recent_decisions(_decisions, limit=20)
    # Decision trace view: real fills as the spine with soft-paired decisions
    # and T+1 verdicts against canonical bars. The DSH plugin renders the same
    # *contract* from its own TypeScript implementation — the two are not shared
    # code, so the parity fixture in tests/test_decision_traces.py is what keeps
    # them honest (#739). Pure read of portfolio.json + ledger + bars.
    _traces = build_decision_traces(limit=40)
    out['decision_traces'] = _traces
    # The card's own totals. Never let it sum its 40-row window and print that
    # as the ledger total (#737).
    out['decision_trace_scope'] = build_decision_trace_scope(_traces, limit=40)
    out['debate_metrics'] = compute_debate_metrics()
    out['magnitude_metrics'] = compute_magnitude_metrics()
    out['plan_timeline'] = compute_plan_timeline(plans, limit=15)
    out['weight_confidence'] = compute_weight_confidence(portfolio)
    # v2.1: broker-style analytics
    fx_rate = (out.get('fx') or {}).get('usdhkd')
    out['drawdown'] = compute_drawdown(snapshots, fx_rate)
    out['sector_exposure'] = compute_sector_exposure(portfolio)
    out['lookthrough_exposure'] = compute_lookthrough_exposure(portfolio)
    out['leveraged_etf'] = compute_leveraged_etf_exposure(portfolio, fx_rate)
    # Tier 2: pull pre-computed risk metrics (from `clawock portfolio-risk`)
    risk_path = WS_ROOT / 'assets' / 'data' / 'risk.json'
    if risk_path.exists():
        try:
            out['risk'] = trim_deep_risk(json.loads(risk_path.read_text()))
        except Exception as e:
            print(f'  warn: risk.json parse fail: {e}', file=sys.stderr)
            out['risk'] = None
    else:
        out['risk'] = None

    # Risk guardrail card — recompute from the LIVE portfolio via the canonical
    # brief_preflight.compute_risk_guardrail (single source of truth) so the dashboard
    # always shows current breaches, not whatever the last brief-context captured.
    # Leverage dial (lev_regime.json) — embed for the 🧭 card AND feed the guardrail
    # recompute so the dashboard's leveraged-ETF cap matches the tightened regime cap.
    lev_regime = None
    lr_path = WS_ROOT / 'assets' / 'data' / 'lev_regime.json'
    if lr_path.exists():
        try:
            lev_regime = json.loads(lr_path.read_text())
        except Exception as e:
            print(f'  warn: lev_regime.json parse fail: {e}', file=sys.stderr)
    # regime_history is ~16KB of per-date series that no chart reads — it exists
    # for the alpha-by-regime bucket and is still published whole in
    # assets/data/lev_regime.json. The page pays for it on every first paint
    # otherwise.
    out['lev_regime'] = trim_lev_regime(lev_regime)
    out['reentry_radar'] = compute_reentry_radar(lev_regime, portfolio)

    out.update(compute_guardrail_outputs(
        portfolio, out.get('risk') or {}, lev_regime=lev_regime))
    annotate_guardrail_history(out.get('risk_guardrail'), load_guardrail_history())

    # Embed GH Action outputs into dashboard.json so the static page can render them
    def _embed(key, fname):
        path = WS_ROOT / 'assets' / 'data' / fname
        if path.exists():
            try:
                out[key] = json.loads(path.read_text())
                return
            except Exception as e:
                print(f'  warn: {fname} parse fail: {e}', file=sys.stderr)
        out[key] = None

    _embed('quant_signals', 'quant_signals.json')      # compute_quant_signals.py: 趋势/动量/RSI/ATR吊灯/vol-target
    _embed('quant_signal_review', 'quant_signal_review.json')  # quant_signal_review.py: 因子 edge 自检(T+1/T+5 对账)
    # Keep only the activation/validation envelope in dashboard.json. The full
    # 38-name research table is a sidecar (~64KB); embedding it would push the
    # public payload past its size cap and evict recent plans.
    _cs_path = WS_ROOT / 'assets' / 'data' / 'cross_sectional_factor.json'
    try:
        _cs = json.loads(_cs_path.read_text()) if _cs_path.exists() else {}
        out['cross_sectional_factor'] = {
            'as_of': _cs.get('as_of'),
            'universe': _cs.get('universe'),
            'validation': _cs.get('validation'),
            'activation': _cs.get('activation'),
        } if _cs else None
    except Exception as e:
        print(f'  warn: cross_sectional_factor.json parse fail: {e}', file=sys.stderr)
        out['cross_sectional_factor'] = None
    _peer_path = WS_ROOT / 'assets' / 'data' / 'peer_residual.json'
    try:
        _peer = json.loads(_peer_path.read_text()) if _peer_path.exists() else {}
        out['peer_residual'] = {
            'as_of': _peer.get('as_of'),
            'taxonomy': _peer.get('taxonomy'),
            'calibration': _peer.get('calibration'),
            'rule_activation': _peer.get('rule_activation'),
        } if _peer else None
    except Exception as e:
        print(f'  warn: peer_residual.json parse fail: {e}', file=sys.stderr)
        out['peer_residual'] = None
    _news_graph_path = (
        WS_ROOT / 'assets' / 'data' / 'news_evidence_graph.json'
    )
    try:
        _news_graph = (
            json.loads(_news_graph_path.read_text())
            if _news_graph_path.exists() else {}
        )
        _news_events = _news_graph.get('events') or []
        out['news_evidence_graph'] = {
            'as_of': _news_graph.get('as_of'),
            'summary': _news_graph.get('summary'),
            'actionable_events': [
                event for event in _news_events
                if event.get('actionable_escalation')
            ],
            'tavily_resolution_queue': (
                _news_graph.get('tavily_resolution_queue') or []
            ),
            'policy': _news_graph.get('policy'),
        } if _news_graph else None
    except Exception as e:
        print(
            f'  warn: news_evidence_graph.json parse fail: {e}',
            file=sys.stderr,
        )
        out['news_evidence_graph'] = None
    _embed('t0_setups', 't0_setups.json')              # compute_t0_setups.py: T+0 牌面评级(追高检测)
    _embed('t0_setup_review', 't0_setup_review.json')  # t0_setup_review.py: 牌面命中率背书(T+1对账)
    _embed('catalysts', 'catalysts.json')              # clawock catalysts + brief preflight
    _embed('benchmark', 'benchmark.json')              # fetch_benchmark_history.py: SPY/HSI/HSTECH daily close
    # 基准新鲜度守卫 — Polygon/HSI 抓取偶发限流会让 benchmark.json 停更(曾停到6天),
    # equity curve 的 SPY/恒科等值线会静默退化成平线。被动暴露 staleness 给前端显示小字
    # 提示(不推送,遵 feedback_no_individual_cron_alerts)。>4 日历日(≈>2交易日,含周末)算停更。
    try:
        _bm = out.get('benchmark')
        if isinstance(_bm, dict):
            _series = _bm.get('series') or {}
            _last = [arr[-1].get('date') for arr in _series.values()
                     if isinstance(arr, list) and arr and arr[-1].get('date')]
            if _last:
                _fresh = max(_last)
                try:
                    _y, _m, _d = map(int, _fresh.split('-'))
                    _behind = (datetime.now().date() - datetime(_y, _m, _d).date()).days
                except Exception:
                    _behind = None
                _bm['staleness'] = {
                    'last_date': _fresh,
                    'days_behind': _behind,
                    'is_stale': (_behind is not None and _behind > 4),
                }
    except Exception as e:
        print(f'  warn: benchmark staleness calc failed: {e}', file=sys.stderr)
    # Option 2 decouple (2026-07-04): the GH-Action / scan sidecars (macro,
    # sentiment, influencer_feed, us_news_digest, em_news) are NO LONGER embedded
    # here — index.html fetches them directly. This makes dashboard.json carry only
    # portfolio-derived data, so a scan's bot commit reaches the page immediately
    # without any dashboard rebuild (true disjoint writers, the endgame Option 1
    # started). Their freshness is still monitored via _FRESHNESS_SLA_H below (that
    # check reads the files from disk, not from `out`).

    # Regime badge stays in dashboard.json (the brief acts on it): read macro.json
    # directly to classify, without embedding the full macro payload. Defensive —
    # never break the build if the file or harness module is unavailable.
    out['regime'] = None
    try:
        _macro_path = WS_ROOT / 'assets' / 'data' / 'macro.json'
        _macro = json.loads(_macro_path.read_text()) if _macro_path.exists() else None
        if _macro:
            from clawock.market_data.macro import classify_regime
            out['regime'] = classify_regime(_macro)
    except Exception as e:
        print(f'  warn: regime classify failed: {e}', file=sys.stderr)

    out['current_holdings_extremes'] = compute_current_holdings_extremes(portfolio, top_n=3)
    out['today_ranges'] = compute_today_ranges(portfolio, top_n=8)
    out['realized_vs_unrealized'] = compute_realized_vs_unrealized(portfolio, fx_rate)
    out['capital_deployed'] = compute_capital_deployed(portfolio, fx_rate)
    out['net_principal_return'] = compute_net_principal_return(portfolio, fx_rate)

    # 🥇 黄金定投卡（000217 华安黄金ETF联接C）— 独立成卡，CNY，不并入跨币种总额
    # （见记忆 openclaw-fx-rule）。数据由 KCNyu gold automation 每日刷进 portfolio.json['gold_dca']，
    # 这里只做体积裁剪后透传。portfolio.json 已 commit，GHA fresh-checkout 也有，无 .tmp 依赖。
    _gold = portfolio.get('gold_dca')
    if _gold:
        _gold = dict(_gold)
        _gold.pop('parent_backtest', None)  # ETF 回测段 2026-06-11 撤除（kcn：没用，就是黄金本身）
        if isinstance(_gold.get('nav_history'), list):
            _gold['nav_history'] = _gold['nav_history'][-90:]  # 迷你图够用，控体积
        if isinstance(_gold.get('london'), dict):
            _gold['london'] = dict(_gold['london'])
            # 结算窗的原始参考序列只属于 fetcher 持久状态；dashboard 只需要
            # 来源、点数和可见 advisory，不把整条内部校验账本发到浏览器。
            _gold['london'].pop('hist_series', None)
            _gold['london'].pop('fx_hist_series', None)
    out['gold_dca'] = _gold

    # A2 健康卡：数据新鲜度 + 体检结论（纯文件运算，零网络）
    try:
        out['build_status'] = compute_build_status(portfolio, OUT_DIR)
    except Exception as e:
        print(f'  warn: compute_build_status failed: {e}', file=sys.stderr)
        out['build_status'] = None
    if isinstance(out.get('build_status'), dict):
        # Provenance for the only values that did not come from the workspace.
        # `preserved: []` is the healthy reading and the one the live host is
        # expected to publish; a non-empty list means this payload is partly a
        # copy of an older one, which a reader is entitled to know. Attached only
        # when the health card was computed — a failed build_status is already
        # its own signal and must keep its `null`.
        out['build_status']['previous_payload'] = {
            'source': workspace_relative(previous_source),
            'preserved': _preserved,
        }
        # Only present when something is wrong, so a healthy payload stays byte
        # for byte what it was. `preserved: []` alone cannot tell "every source
        # was present" from "the recovery file was not there" (#314).
        if _previous_missing:
            out['build_status']['previous_payload']['missing'] = True
    if brief_ctx_path:
        print(f'  brief-context source: {os.path.basename(brief_ctx_path)}')

    # The size cap trims `out` and the overview is compiled from the trimmed
    # result, so both stay part of the projection: they change what the payload
    # IS, not where it goes. Only the writes belong to the caller.
    #
    # dashboard.json is the canonical cross-tab browser document. Keep it compact:
    # detail activation still pays this parse, and producers should not spend
    # recovered headroom on indentation that adds no user value.
    payload = dashboard_wire_payload(out)
    size_bytes = len(payload.encode('utf-8'))

    if size_bytes > MAX_OUT_BYTES:
        # Last resort: drop recent_plans entirely + keep snapshot summaries only
        print(f'⚠️  payload still {size_bytes} bytes > {MAX_OUT_BYTES} cap — dropping recent_plans', file=sys.stderr)
        out['recent_plans'] = []
        out['recent_plans_dropped'] = True
        payload = dashboard_wire_payload(out)
        size_bytes = len(payload.encode('utf-8'))
        if size_bytes > MAX_OUT_BYTES:
            # Second lever: shorten the embedded snapshot series from the OLD
            # end. It is the largest single section (37KB of 195KB at 76 rows,
            # ~489 bytes each) and the only one that grows by one row every
            # trading day, so it — not `recent_plans` — is what actually walks
            # this payload into the cap. Measured 2026-08-26: 195,680 bytes with
            # 4,320 to spare and MAX_SNAPSHOTS_EMBEDDED=90 still 14 rows away,
            # i.e. the cap arrives in ~9 trading days and then stays breached.
            #
            # Oldest-first, because the equity curve's recent shape is what is
            # read; and never below MIN_SNAPSHOTS_UNDER_BUDGET, because past
            # that point the trim stops being cosmetic.
            kept = list(out.get('snapshots') or [])
            dropped = 0
            while (size_bytes > MAX_OUT_BYTES
                   and len(kept) > MIN_SNAPSHOTS_UNDER_BUDGET):
                kept.pop(0)
                dropped += 1
                out['snapshots'] = kept
                payload = dashboard_wire_payload(out)
                size_bytes = len(payload.encode('utf-8'))
            if dropped:
                # Recorded IN the payload, not only on stderr: `recent_plans`
                # already learned this lesson (`recent_plans_dropped`), and a
                # degradation that lives only in a build log is one no gate can
                # read back.
                out['snapshots_trimmed_for_budget'] = dropped
                payload = dashboard_wire_payload(out)
                size_bytes = len(payload.encode('utf-8'))
                print(f'⚠️  dropped the {dropped} oldest snapshot(s) to fit the '
                      f'{MAX_OUT_BYTES} cap — now {size_bytes} bytes', file=sys.stderr)
        if size_bytes > MAX_OUT_BYTES:
            # Both levers spent; publishing an oversized payload still beats not
            # publishing, but say so — on 2026-07-28 the file shipped 3.7KB over
            # the cap with only the line above to show for it, which reads as
            # "handled".
            #
            # Recorded IN the payload as well (#1215). A stderr line reaches no
            # gate: not the build card, not the cron log, not watchdog.jsonl. So
            # the 2026-07-28 breach was invisible to everything that could have
            # acted on it, and "publishing over cap" was a decision nothing
            # downstream could see had been taken. `recent_plans_dropped` and
            # `snapshots_trimmed_for_budget` already live here for this reason;
            # the terminal case was the one that did not.
            #
            # Writing it grows the payload by ~60 bytes, which is the right
            # trade in a branch that is already over: a breach that is 60 bytes
            # worse and legible beats one that is silent.
            # `bytes` is the size with both levers spent and before this marker
            # was added, which is a fixed number; recording the post-marker size
            # would be a value that changes itself.
            out['payload_over_cap'] = {
                'bytes': size_bytes,
                'cap': MAX_OUT_BYTES,
                'over_by': size_bytes - MAX_OUT_BYTES,
                'levers_spent': ['recent_plans', 'snapshots'],
                'measured': 'before this marker was written',
            }
            payload = dashboard_wire_payload(out)
            size_bytes = len(payload.encode('utf-8'))
            print(f'⚠️  payload STILL {size_bytes} bytes > {MAX_OUT_BYTES} cap after '
                  f'dropping recent_plans and trimming snapshots — publishing over cap',
                  file=sys.stderr)

    overview_payload = serialize_dashboard_payload(compile_overview_projection(out))
    overview_size = len(overview_payload.encode('utf-8'))
    if overview_size > MAX_OVERVIEW_BYTES:
        raise ValueError(
            f'overview projection {overview_size:,} bytes exceeds '
            f'{MAX_OVERVIEW_BYTES:,}-byte cap')

    return {
        # Serialized, because the size caps above are enforced on the encoded
        # bytes: handing back the dict would let a writer re-encode differently
        # and publish something the cap never saw.
        'dashboard': payload,
        'overview': overview_payload,
        'audit': json.dumps(_audit, ensure_ascii=False, separators=(',', ':')),
        'shadow': json.dumps(_shadow, ensure_ascii=False, indent=2) + '\n',
        # What the caller needs to record the slice-2 telemetry without knowing
        # how the merge works.
        'preservation': {'presence': _presence, 'preserved': _preserved,
                         'missing': _previous_missing},
        'summary': {
            'dashboard_bytes': size_bytes,
            'overview_bytes': overview_size,
            'us_holdings': len(us_h),
            'us_active': len([h for h in us_h if h['is_active']]),
            'us_value': us_conc['total'],
            'hk_holdings': len(hk_h),
            'hk_active': len([h for h in hk_h if h['is_active']]),
            'hk_value': hk_conc['total'],
            'snapshots_embedded': len(snapshots),
            'snapshots_total': out['snapshots_total'],
            'plans_embedded': len(plans),
            'plans_total': out['plans_count'],
            'fx_rate': fx_cache.get('rate'),
            'fx_source': fx_cache.get('source'),
        },
    }


def main(argv=None):
    # BUILD_DASHBOARD_OUT: redirect the WRITE target only. Verification callers
    # (system_check's buildability gate, run by the pre-push hook) build to a
    # temp file so a *check* never mutates the published artifact — before
    # 2026-06-10 every pre-push run rewrote dashboard.json in place, leaving
    # the working tree perpetually dirty. A redirected build still reads whatever
    # `--previous` names, so the redirect never changes which cards are restored.
    args = parse_args(argv)
    # Input fingerprint gate (#846): the 20-minute publisher runs ~72x/day, and
    # the harness postflights ~23 more — most of them against an unchanged desk.
    # The fingerprint is stat-level, so computing it is µs; the build it skips
    # is ~12MB of JSON parsing plus a full settlement pass.
    gate_fingerprint: str | None = None
    if args.skip_if_unchanged:
        gate_fingerprint = dashboard_input_fingerprint(WS_ROOT)
        if _read_fingerprint_cache(WS_ROOT) == gate_fingerprint:
            print('dashboard-build: inputs unchanged — skipping rebuild (#846)')
            return 0
    previous_source = resolve_previous_source(args)
    # The four outputs are one logical generation (clawock.publish.outputs owns that
    # contract). Their paths are resolved together, here, so that the projection
    # never learns where it is going to land.
    paths = resolve_output_paths(args.out_dir)
    out_file, overview_file = paths['dashboard'], paths['overview']
    audit_file, shadow_file = paths['audit'], paths['shadow']
    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        projection = build_projection(
            previous_source=previous_source,
            shadow_previous=load_json(shadow_file) if shadow_file.exists() else None)
    except MissingPortfolio:
        print('FATAL: portfolio.json missing', file=sys.stderr)
        return 1
    except ProjectionInputError as e:
        # Same exit code the buildability gate already reads, but say which input
        # is wrong — "portfolio.json missing" would be a lie here.
        print(f'FATAL: {e}', file=sys.stderr)
        return 1

    # All four are compiled from the same in-memory generation and enter the
    # shared publication pathspec together, so they are published as one write
    # set: every file is staged on disk before any of them is swapped in. A
    # failure part-way now publishes nothing instead of two new files beside two
    # old ones (#262 slice 3 step 3). The browser still verifies their generation
    # IDs, because intermediary caches need not be atomic either way.
    #
    # Order is the ownership contract's, so the pathspec and the write set cannot
    # drift apart.
    dashboard_outputs.write_generation({
        str(overview_file): projection['overview'],
        str(out_file): projection['dashboard'],
        str(audit_file): projection['audit'],
        str(shadow_file): projection['shadow'],
    })

    record_preservation(
        projection['preservation']['presence'],
        projection['preservation']['preserved'],
        previous_source, out_file,
        missing=projection['preservation']['missing'])

    s = projection['summary']
    print(f'✓ wrote {overview_file} ({s["overview_bytes"]:,} bytes)')
    print(f'✓ wrote {out_file} ({s["dashboard_bytes"]:,} bytes)')
    print(f'✓ wrote {audit_file} (decision audit sidecar)')
    print(f'✓ wrote {shadow_file} (shadow portfolio sidecar, 模拟·非实盘)')
    print(f'  US: {s["us_holdings"]} holdings, {s["us_active"]} active, value ${s["us_value"]:.0f}')
    print(f'  HK: {s["hk_holdings"]} holdings, {s["hk_active"]} active, value HK${s["hk_value"]:.0f}')
    print(f'  Snapshots: {s["snapshots_embedded"]} embedded / {s["snapshots_total"]} on disk')
    print(f'  Plans: {s["plans_embedded"]} embedded / {s["plans_total"]} on disk')
    print(f'  Snapshots: {s["snapshots_embedded"]} | Plans: {s["plans_embedded"]}')
    print(f'  FX USDHKD: {s["fx_rate"]} ({s["fx_source"]})')
    if gate_fingerprint is not None:
        _write_fingerprint_cache(WS_ROOT, gate_fingerprint)
    return 0


if __name__ == '__main__':
    sys.exit(main())
