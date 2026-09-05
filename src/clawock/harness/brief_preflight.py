#!/usr/bin/env python3
"""
brief_preflight.py — deterministic data collection for daily-deep-brief harness.

Runs everything that must happen BEFORE LLM analysis. It keeps a complete audit
context, then emits a budgeted core plus generation-bound lazy bundles for the
LLM (FX rate, concentration, retrospective, etc.) so it cannot forget steps or
silently absorb an unbounded monolith.

Steps:
  1. Refresh US + HK prices (mutates portfolio.json)
  2. Fetch FX rate (3-route fallback)
  3. Snapshot portfolio.json → memory/snapshots/{date}.json
  4. Compute HHI concentration + Top2 for HK and US legs
  5. Compute USD-base / HKD-base book totals
  6. Pull SEC EDGAR fundamentals for US singles (is_leveraged_etf=false)
  7. Locate prior plan.json + compute retrospective (trigger fired + simulated PnL)
  8. Peer scan
  9. Self-calibration
 10. Risk metrics
 11. Catalyst calendar (next 14d earnings + FOMC + macro)
 12. Benchmark history (SPY + HSI/HSTECH) for equity curve overlay
 13. Load macro + sentiment snapshots (read assets/data/{macro,sentiment}.json)
 14. Write the full audit context + model-facing manifest/core/bundles

Output (stdout): step-by-step progress; final summary with issue count.
Exit: 0 if no issues, 1 if any data leg failed.
"""

from clawock.portfolio.guardrail import (  # noqa: F401  (re-export)
    GUARDRAIL_CAPS,
    LEV_1X_SWAP,
    _holding_pnl_pct,
    _is_leveraged_etf,
    _swap_suggestions,
    compute_breakeven_math,
    compute_concentration,
    compute_risk_guardrail,
)
import argparse
import concurrent.futures
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo

from clawock.workspace import workspace_root
from clawock import sessions as trading_calendar
from clawock import history_store
from clawock.context import brief as brief_context
from clawock.decision import ledger as decision_v2
from clawock.decision import packet as brief_decision_packet
from clawock.decision import add_side
from clawock.decision import signals as bar_signals
from clawock.decision import plans as decision_plans
from clawock.decision import risk as risk_discipline
from clawock.decision import theses as thesis_registry
from clawock.decision import watch_list as watch_list_scan
from clawock.evidence import research_surface
from clawock.market_data import mover_evidence as mover_news
from clawock.market_data import peer_scan

WS = workspace_root()
_CHECKOUT = WS
TMP_DIR = WS / 'memory' / '.tmp'
SNAPSHOT_DIR = WS / 'memory' / 'snapshots'

from clawock.automation import workflow_outcomes  # noqa: E402
from clawock.market_data.macro import classify_regime as _classify_regime  # noqa: E402
from clawock.instruments import get as get_instrument  # noqa: E402
from clawock.instruments import is_leveraged_holding  # noqa: E402
from clawock.instruments import compute_lookthrough_exposure  # noqa: E402
from clawock.instruments import one_x_swap_map  # noqa: E402


def _fetch_hk_results_notices(ticker):
    """KCNyu's free HK notice feed; core only consumes injected records."""
    symbol = mover_news.tencent_symbol(ticker, "hk")
    if not symbol:
        return []
    payload = mover_news._http_json(
        f"{mover_news.TENCENT_NEWS}?symbol={symbol}&n=20&page=1&type=0"
    )
    return ((payload or {}).get("data") or {}).get("data") or []


def _run(script, args=None, timeout=120):
    """Run a workspace script; return (stdout, ok)."""
    cmd = ['python3', str(WS / script)] + (args or [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.returncode == 0
    except Exception as e:
        return f'{type(e).__name__}: {e}', False


def clawock_argv(command, *args):
    """argv for one package command, run through *this* interpreter (#918).

    Spawning the bare console script makes every one of these steps depend on
    whatever is on PATH — and the failure mode is quiet: under the user
    crontab's ``PATH=/usr/bin:/bin`` the entry point is simply not there,
    ``FileNotFoundError`` gets swallowed by the callers' broad excepts, and the
    step reports that it did nothing wrong. ``sys.executable -m clawock`` runs
    the package that is actually imported here, so there is no second install
    to keep in sync and no PATH to get wrong.
    """
    return [sys.executable, '-m', 'clawock', command, *args]


def _run_clawock(command, args=None, timeout=120):
    """Run one package command in the selected workspace."""
    try:
        result = subprocess.run(
            clawock_argv(command, *(args or [])), cwd=WS,
            capture_output=True, text=True, timeout=timeout)
        return (result.stdout or '') + (result.stderr or ''), result.returncode == 0
    except Exception as exc:
        return f'{type(exc).__name__}: {exc}', False


def _action_track_record():
    """How each kind of advice has actually settled, for the brief to print.

    The brief tells kcn to cut 700 shares at confidence 0.92 and says nothing
    about how the last two hundred cuts went. They went 112–101 (52.6%) at T+1,
    which is a coin flip, and a reader who knew that would read the same
    sentence differently. Counting is all this does: the outcomes were already
    written by `settle_decisions`, and `not_triggered` is kept separate because
    a conditional order that never filled is not a wrong call.
    """
    try:
        rows = decision_v2.load_decisions()
    except Exception as exc:  # noqa: BLE001 — the brief must survive a bad ledger
        return {'error': f'{type(exc).__name__}: {exc}'[:160], 'by_action': {}}
    tally = {}
    for row in rows:
        action = row.get('action')
        outcome = ((row.get('evaluation') or {}).get('outcome'))
        if not action or outcome not in ('win', 'loss', 'flat', 'not_triggered'):
            continue
        seat = tally.setdefault(action, {'win': 0, 'loss': 0, 'flat': 0, 'not_triggered': 0})
        seat[outcome] += 1
    for action, seat in tally.items():
        settled = seat['win'] + seat['loss'] + seat['flat']
        seat['settled'] = settled
        seat['hit_rate'] = round(seat['win'] / settled, 4) if settled else None
    return {'horizon': 'T+1 (evaluation.outcome, fill assumed)',
            'by_action': tally}


def _opportunity_reads(open_decisions):
    """The add side of the book, read off the settled daily bars.

    WHY THIS EXISTS. Until 2026-09-05 the brief context carried 34 fields and
    not one of them was an opportunity: portfolio, guardrail, discipline, macro,
    sentiment, quant signals — every input described risk or state. The model
    that writes the day's decisions therefore never saw a breakout, and the
    ledger shows exactly that: 789 decisions in which `risk_rule` (which does
    get an explicit "cut N shares" input) wrote 135 cuts at mean confidence
    0.81, while `catalyst`/`macro`/`sentiment`/`peer` wrote `hold_and_watch`
    145 times out of 148. Between 07-20 and 09-05 the bar store held 48
    close-confirmed breakouts across 18 names and the ledger recorded zero add
    decisions — not because the desk decided against them, because the process
    that writes decisions could not see them.

    Nothing here authorises anything, and nothing here is a new rule: the states
    come from `add_side.classify_level`, the thresholds from
    `config/add-alpha-policy.json`, the numbers from `signals.compute_signals`
    over `memory/bars`, and the verdicts from the same `add_side.read_rows` the
    intraday slot uses — with `close_confirmed=True`, because this reader is
    looking at closes the market actually printed rather than a live quote.
    """
    try:
        policy = json.loads((WS / 'config' / 'add-alpha-policy.json').read_text())
    except Exception:  # noqa: BLE001 — a missing policy must not red the brief
        policy = {}
    raw_near, raw_z = policy.get('opportunity_near_pct'), policy.get('early_no_chase_zscore')
    near_pct = float(raw_near) if raw_near is not None else 5.0
    no_chase_z = float(raw_z) if raw_z is not None else 2.0

    signals_by_label, unreadable = {}, []
    bars_dir = WS / 'memory' / 'bars'
    for path in sorted(bars_dir.glob('*.json')):
        label = path.stem
        try:
            doc = json.loads(path.read_text())
            if doc.get('retired'):
                continue
            store = doc.get('bars') or {}
            rows = [{'date': day, **{k: store[day][k] for k in ('open', 'high', 'low', 'close')}}
                    for day in sorted(store)
                    if all(store[day].get(k) is not None for k in ('open', 'high', 'low', 'close'))]
            signals_by_label[label] = bar_signals.compute_signals(rows)
        except Exception as exc:  # noqa: BLE001 — one bad file is not a red cron
            unreadable.append({'label': label, 'error': f'{type(exc).__name__}: {exc}'[:160]})

    radar = add_side.daily_radar(signals_by_label, near_pct=near_pct, no_chase_z=no_chase_z)
    reads = add_side.read_rows(radar=radar, levels=radar.get('levels'),
                               plan_context=open_decisions, close_confirmed=True)
    rows = reads['rows']

    # A silent zero is what produced 「为什么只有卖出」— say which of the three
    # reasons it was, so an empty add side is an answer and not an absence.
    over = [r for r in (radar.get('rows') or []) if r['state'] == 'wait_rebreak']
    if reads['candidate_count']:
        why_none = None
    elif not signals_by_label:
        why_none = '没有可读的日线（memory/bars 空或全部不可解析）'
    elif over:
        # The most informative zero of the three: the breakout DID happen and
        # the no-chase filter demoted it. Naming the names and the z is what
        # lets kcn argue with the threshold instead of with the silence.
        names = '、'.join(f"{r['label']} z={r['zscore20']}" for r in over[:4])
        why_none = (f'{len(over)} 只已收盘站上前 20 日高，但 z≥{no_chase_z:g} 判为追高'
                    f'（policy: 等回踩不破再谈）：{names}')
    elif reads['reject_count']:
        why_none = (f"{reads['reject_count']} 只被未了结的纪律动作挡住"
                    f"（先把 cut/trim 走完，再谈加仓）")
    else:
        nearest = sorted(((v.get('pct_from_high'), k)
                          for k, v in (radar.get('levels') or {}).items()
                          if v.get('pct_from_high') is not None), reverse=True)[:3]
        near_txt = '、'.join(f'{k} {p:+.1f}%' for p, k in nearest) or '无可比价位'
        why_none = (f'全部持仓收盘未站上前 20 日高，最接近的三只：{near_txt}'
                    f'（突破是唯一有回测边缘的加仓形态，#819）')

    return {
        'schema_version': 1,
        'confirmed_at_close': True,
        'policy': reads['policy'],
        'near_pct': near_pct,
        'no_chase_zscore': no_chase_z,
        'counts': {'candidate': reads['candidate_count'],
                   'wait': reads['wait_count'],
                   'reject': reads['reject_count']},
        'rows': rows,
        'levels': radar.get('levels') or {},
        'why_no_candidate': why_none,
        'unreadable': unreadable,
    }


def _technical_setup_usage():
    """Count every broker-observed setup tranche, regardless of alpha driver."""
    usage = {}
    for row in decision_v2.load_decisions():
        setup_id = row.get('technical_setup_id')
        campaign_id = row.get('technical_campaign_id')
        if (row.get('action') not in decision_v2.ADD_ACTIONS
                or not setup_id or not campaign_id
                or (row.get('execution') or {}).get('status') != 'followed'):
            continue
        ticker = str(row.get('ticker') or '')
        by_setup = usage.setdefault(ticker, {})
        by_setup[campaign_id] = by_setup.get(campaign_id, 0) + 1
    return usage


def fetch_fx_rate():
    try:
        result = subprocess.run(
            clawock_argv('fx', '--json'), cwd=WS, capture_output=True,
            text=True, timeout=30)
        out, ok = result.stdout, result.returncode == 0
    except Exception as exc:
        out, ok = f'{type(exc).__name__}: {exc}', False
    if not ok:
        return {'rate': 7.80, 'source': 'HARDCODED_FALLBACK', 'error': out[-300:]}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {'rate': 7.80, 'source': 'PARSE_FAILED', 'error': out[-300:]}




def collect_us_fundamentals(portfolio):
    """Pull SEC EDGAR --financials for the non-leveraged US singles, in one spawn.

    One process for the whole list, not one per ticker (#918). The SEC throttle
    inside ``market_data.filings`` is an in-process ``_last_call``, so N spawns
    hold N independent limiters — which is why this loop could never simply be
    parallelised, and why the batch mode exists instead. Sequential inside that
    single process keeps the desk's request rate the one it declares.
    """
    tickers = [h['ticker'] for h in portfolio['portfolios']['us_stocks']['holdings']
               if h.get('shares', 0) > 0 and not _is_leveraged_etf(h)]
    if not tickers:
        return {}
    # 单只时保持原来的单只形状；两只以上走 batch。超时按只数给，别让第五只
    # 去挤第一只的预算。
    timeout = 30 if len(tickers) == 1 else 20 * len(tickers)
    try:
        result = subprocess.run(
            clawock_argv('filings', *tickers, '--financials', '--json'),
            cwd=WS, capture_output=True, text=True, timeout=timeout,
        )
        out, ok = result.stdout, result.returncode == 0
    except Exception as exc:
        out, ok = f'{type(exc).__name__}: {exc}', False
    if not ok:
        return {ticker: {'error': out[-300:]} for ticker in tickers}
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return {ticker: {'error': 'parse failed', 'raw': out[:300]}
                for ticker in tickers}
    if len(tickers) == 1:
        return {tickers[0]: payload}
    batch = payload.get('batch') or {}
    return {ticker: batch.get(ticker, {'error': 'missing from batch response'})
            for ticker in tickers}













GUARDRAIL_HISTORY = WS / 'assets' / 'data' / 'guardrail_history.jsonl'


def _append_guardrail_history(today, guardrail, hk_conc, us_conc, risk):
    """Persist the day's guardrail verdict so its value becomes measurable.

    The caps are the part of this system that demonstrably works — the 2026-06
    drawdown was a construction problem, and they exist to stop it recurring. But
    they were recomputed into gitignored tmp every morning and thrown away, so
    "what did the guardrail prevent?" had no data behind it while every timing
    call was scored to four decimals. One row per brief, appended, idempotent by
    date. Nothing can be reconstructed retroactively, so this starts today and
    accrues; do not expect a verdict from it for some weeks.
    """
    try:
        row = {
            'date': today,
            'breach_count': guardrail.get('breach_count'),
            'breaches': [{k: b.get(k) for k in ('type', 'leg', 'ticker', 'severity', 'detail')}
                         for b in (guardrail.get('breaches') or [])],
            'hard_stop_watch': [{k: h.get(k) for k in ('ticker', 'leg', 'pnl_pct')}
                                for h in (guardrail.get('hard_stop_watch') or [])],
            'eff_lev_caps': guardrail.get('eff_lev_caps'),
            'lev_regime_tier': ((guardrail.get('lev_regime') or {}).get('tier')),
            'hk_top2_pct': (hk_conc or {}).get('top2_pct'),
            'us_top2_pct': (us_conc or {}).get('top2_pct'),
            'us_beta_spx': ((risk or {}).get('us') or {}).get('beta_spx'),
        }
        existing = []
        if GUARDRAIL_HISTORY.exists():
            existing = [l for l in GUARDRAIL_HISTORY.read_text().splitlines()
                        if l.strip() and json.loads(l).get('date') != today]
        GUARDRAIL_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        GUARDRAIL_HISTORY.write_text(
            ''.join(l + '\n' for l in existing)
            + json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
        print(f'  guardrail_history: {today} ({row["breach_count"]} breaches)')
    except Exception as e:  # never block the brief on bookkeeping
        print(f'warn: guardrail history append failed: {e}', file=sys.stderr)




def find_prior_plan(today_iso):
    """Most recent memory/*-plan.json with filename date < today."""
    candidates = sorted((WS / 'memory').glob('*-plan.json'))
    today_filename = f'{today_iso}-plan.json'
    prior = [p for p in candidates if p.name < today_filename]
    return prior[-1] if prior else None


def _is_hk_ticker(t):
    return t.isdigit() and len(t) <= 5


def compute_retrospective(prior_plan_path, portfolio, ledger_decisions=None):
    """Yesterday's plan, scored by the settled ledger — never by a snapshot.

    Until #964 this function recomputed its own trigger verdicts from the
    portfolio snapshot's ``current_price`` / ``day_open`` / ``day_high`` /
    ``day_low``. Those fields carry the vintage of whichever cron last fetched,
    not of a trading session — the repo's own ``market_data/bars`` docstring
    lists the damage (00100 showed one identical (high, low) across four
    different sessions; ``current_price`` was the previous close in half the
    snapshots). So the same decision could carry two contradictory verdicts in
    one context bundle: the ledger's, settled against canonical bars, and this
    one's. The LLM was fed both and asked to calibrate confidence on them.

    There is now one verdict per decision, and it is the ledger's. This function
    only *joins*: plan-side facts (what was authorised, at what confidence) meet
    ``evaluation`` (what the bars say happened), and every scored field carries
    ``verdict_source`` so a reader can tell join from judgement. The money-shaped
    ``simulated_pnl`` is gone with the snapshot prices it was made of;
    ``benefit_t1_pct`` from the ledger is the same question answered against
    session-dated bars.
    """
    if not prior_plan_path:
        return {'prior_plan_date': None, 'decisions': [], 'note': 'first run (no prior plan)'}

    try:
        prior = json.loads(prior_plan_path.read_text())
    except Exception as e:
        return {'error': f'parse prior plan failed: {e}', 'path': str(prior_plan_path)}

    all_holdings = (portfolio['portfolios']['hk_stocks']['holdings'] +
                    portfolio['portfolios']['us_stocks']['holdings'])
    held = {h['ticker'] for h in all_holdings}

    by_id = {}
    by_plan = {}
    for settled in ledger_decisions or []:
        if settled.get('decision_id'):
            by_id[settled['decision_id']] = settled
        by_plan.setdefault(
            (settled.get('plan_date'), settled.get('ticker'), settled.get('action')),
            settled,
        )

    results = []
    for action in prior.get('decisions', []):
        ticker = action.get('ticker')
        bucket = action.get('action', '')
        condition = action.get('condition') or {}
        # decision_id is the join key; the (date, ticker, action) fallback covers
        # plans authored before ids existed. A miss is reported as a miss — an
        # unsettled decision must not be silently scored here, because "score it
        # myself" is exactly the second implementation #964 removed.
        settled = (by_id.get(action.get('decision_id'))
                   or by_plan.get((prior.get('date'), ticker, bucket)))
        evaluation = (settled or {}).get('evaluation') or {}

        session = evaluation.get('trigger_session')
        if settled is not None and not session:
            session, _reason = decision_v2.evaluation_session(settled)
        day_bar = decision_v2.bar(ticker, session) if session else None

        results.append({
            'ticker':                   ticker,
            'decision_id':              action.get('decision_id'),
            'episode_id':               action.get('episode_id'),
            'thesis_id':                action.get('thesis_id'),
            'strategy_id':              action.get('strategy_id'),
            'action':                   bucket,
            'plan_trigger_type':        condition.get('type', 'manual'),
            'plan_trigger_price':       condition.get('price'),
            'plan_size_shares':         (action.get('size') or {}).get('shares'),
            'plan_confidence':          action.get('confidence'),
            'plan_rationale':           action.get('rationale'),
            'still_held':               ticker in held,
            # —— 以下全部来自 decision_v2 的结算，本函数不自己判 ——
            'trigger_fired':            evaluation.get('triggered'),
            'trigger_session':          session,
            'settlement_status':        evaluation.get('status'),
            'outcome':                  evaluation.get('outcome'),
            'execution_price':          (evaluation.get('execution_price')
                                         if evaluation.get('execution_price') is not None
                                         else evaluation.get('reference_price')),
            'benefit_t1_pct':           evaluation.get('benefit_t1_pct'),
            'session_bar':              ({k: day_bar[k] for k in ('open', 'high', 'low', 'close')}
                                         if day_bar else None),
            'verdict_source':           ('decision_ledger' if settled is not None
                                         else 'unsettled_no_ledger_row'),
            'verdict_basis':            'memory/bars (session-dated, unadjusted)',
            'verdict_note':             (evaluation.get('not_evaluable_reason')
                                         or evaluation.get('pending_reason')
                                         or evaluation.get('fill_reason')),
        })

    # Confidence calibration buckets
    def _calib(lo, hi):
        scored = [r for r in results
                  if r.get('plan_confidence') is not None
                  and lo <= r['plan_confidence'] < hi
                  and r['trigger_fired'] is not None]
        fired = sum(1 for r in scored if r['trigger_fired'])
        return f'{fired}/{len(scored)}' if scored else 'n/a'

    return {
        'prior_plan_date': prior.get('date'),
        'prior_plan_path': str(prior_plan_path),
        'verdict_source': 'decision_v2 ledger settled against memory/bars',
        'decisions':       results,
        'confidence_calibration': {
            'conf_80_100':  _calib(0.80, 1.01),
            'conf_60_79':   _calib(0.60, 0.80),
            'conf_below_60': _calib(0.0,  0.60),
        },
    }


def collect_peer_scan(portfolio):
    """Delegates to the shared peer scanner (also used by report_preflight)."""
    return peer_scan.collect(portfolio)


# Two-level memo for the follow-up verification sweep (#916): every decision
# row asks the same one-or-two dates, and each ask used to cost a `git log`
# plus a `git show` with a full JSON re-parse (~5s/slot of pure re-read).
_shares_sha_cache = {}   # date_iso -> commit sha
_shares_pf_cache = {}    # sha -> parsed portfolio.json


def _shares_at_date(ticker, date_iso):
    """Get shares of `ticker` from portfolio.json as committed on/before `date_iso`.
    Returns int shares, or None if can't determine.

    Past-date answers are immutable — today's commits cannot rewrite what was
    HEAD before a past day — so the caches are exact there. A today-keyed sha
    can go stale if a bot commits mid-preflight; the verdict self-heals on the
    next slot's fresh process.
    """
    try:
        sha = _shares_sha_cache.get(date_iso)
        if sha is None:
            r = subprocess.run(
                ['git', '-C', str(WS), 'log', '--pretty=%H',
                 f'--before={date_iso} 23:59:59', '-1', '--', 'portfolio.json'],
                capture_output=True, text=True, timeout=10)
            sha = r.stdout.strip()
            if not sha:
                return None
            _shares_sha_cache[date_iso] = sha
        pf = _shares_pf_cache.get(sha)
        if pf is None:
            r = subprocess.run(['git', '-C', str(WS), 'show', f'{sha}:portfolio.json'],
                               capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                return None
            try:
                pf = json.loads(r.stdout)
            except ValueError:
                return None
            _shares_pf_cache[sha] = pf
        for region in ('hk_stocks', 'us_stocks'):
            for h in pf['portfolios'][region]['holdings']:
                if h['ticker'] == ticker:
                    return int(h.get('shares', 0))
    except Exception:
        pass
    return None


def _detect_followed(row, min_window_days=None):
    """Compare shares on plan_date vs T+N. Return 'true' / 'false' / 'unknown'.

    Bucket → expected delta:
      cut / trim_on_rebound → shares should DECREASE
      add_only_on_trigger / add_on_breakout → shares should INCREASE
      hold_and_watch / watch / t_only → shares should be UNCHANGED

    min_window_days defaults to `decision_v2.verification_window_days`:
      hold_and_watch / watch / t_only → T+1 (held by next day = followed)
      cut / trim / add → T+2 (give user a working day to actually trade)
    """
    plan_date = row.get('plan_date')
    ticker = row.get('ticker')
    bucket = row.get('bucket', '').lower()
    if not (plan_date and ticker):
        return 'unknown'

    if min_window_days is None:
        # One definition, in decision_v2: _exec_rate needs the identical rule to
        # separate "not verifiable yet" from "never will be", and a second copy
        # here would drift without anything failing.
        condition = row.get('condition') or {}
        min_window_days = decision_v2.verification_window_days(
            bucket,
            plan_date=plan_date,
            leg=row.get('leg'),
            valid_for_sessions=condition.get('valid_for_sessions'),
        )

    # Day BEFORE plan_date (last commit before plan was created)
    try:
        plan_dt = datetime.strptime(plan_date, '%Y-%m-%d')
        before_dt = (plan_dt - timedelta(days=1)).strftime('%Y-%m-%d')
        after_dt = (plan_dt + timedelta(days=min_window_days)).strftime('%Y-%m-%d')
    except Exception:
        return 'unknown'

    # don't look ahead if window end is in the future
    if datetime.now() < plan_dt + timedelta(days=min_window_days):
        return 'unknown'  # too early; will retry next preflight

    shares_before = _shares_at_date(ticker, before_dt)
    shares_after  = _shares_at_date(ticker, after_dt)
    if shares_before is None or shares_after is None:
        return 'unknown'

    delta = shares_after - shares_before

    # Apply bucket rule
    if bucket in ('cut', 'trim_on_rebound'):
        return 'true' if delta < 0 else 'false'
    if bucket in ('add_only_on_trigger', 'add_on_breakout'):
        return 'true' if delta > 0 else 'false'
    if bucket in ('hold_and_watch', 'watch', 't_only'):
        return 'true' if delta == 0 else 'false'  # you held → followed; you bought/sold → didn't follow plan
    return 'unknown'  # 未识别 bucket




def compute_reflections(portfolio):
    """Episode-level lessons for currently held tickers."""
    rows = decision_v2.episode_representatives(decision_v2.load_decisions(), 't1')

    held = {h['ticker'] for leg in ('hk_stocks', 'us_stocks')
            for h in portfolio['portfolios'][leg]['holdings'] if h.get('shares', 0) > 0}
    SELL = {'cut', 'trim_on_rebound'}
    out = {}
    for tk in sorted(held):
        settled = [r for r in rows if r['ticker'] == tk and (r.get('evaluation') or {}).get('outcome') in ('win', 'loss')]
        if not settled:
            continue
        settled.sort(key=lambda r: r['plan_date'])
        wins = sum(1 for r in settled if (r.get('evaluation') or {}).get('outcome') == 'win')
        # dominant bucket history + a plain lesson
        by_b = {}
        for r in settled:
            by_b.setdefault(r['action'], []).append(r)
        lessons = []
        for b, rs in by_b.items():
            w = sum(1 for r in rs if (r.get('evaluation') or {}).get('outcome') == 'win')
            verb = {'cut': '清', 'trim_on_rebound': '减', 'add_only_on_trigger': '加',
                    'hold_and_watch': '持', 't_only': 'T'}.get(b, b)
            lessons.append(f'{verb}×{len(rs)} 胜{w}')
        recent = settled[-3:]
        out[tk] = {
            'n': len(settled),
            'win_rate': round(wins / len(settled), 2),
            'bucket_history': '; '.join(lessons),
            'recent': [{'date': r['plan_date'], 'strategy_id': r.get('strategy_id'),
                        'action': r['action'], 'conf': r.get('confidence'),
                        'outcome': (r.get('evaluation') or {}).get('outcome'),
                        'benefit_pct': (r.get('evaluation') or {}).get('benefit_t1_pct')} for r in recent],
            'lesson': (f'{tk}: 过去 {len(settled)} 个策略 episode 胜率 {wins/len(settled):.0%}'
                       + ('（主动 call 多半没跑赢持有，本次谨慎）' if wins / len(settled) < 0.5 else '')),
        }
    return out


def trim_abstaining_calibrators(metrics):
    """Inject only the calibrator rows that can still change a sizing decision.

    `hierarchical_calibration.current_group_calibrators` is one row of beta-binomial
    posterior state per `action + driver + condition + regime` group. On 2026-07-27
    that was 42 rows / 27KB — 10.7% of the whole injected context, re-sent on every
    turn of a 17-minute multi-turn run. `build_dashboard.trim_decision_metrics`
    already drops the same block from the public payload (#102); the brief, which
    pays for it far more often, kept shipping all of it.

    Dropping the abstaining rows is behaviour-preserving because both skills that
    read this table define a missing row and an abstaining row as the same outcome:
    "找不到完全匹配行：按 abstain 处理" (daily-deep-brief), "A missing exact row,
    `abstain=true`, or `edge_supported=false` means the signal contributes zero
    incremental size" (portfolio-swarm-review).

    The filter is `evidence_sufficient`, not `edge_supported`, on purpose.
    decision_v2 defines `edge_supported = not abstain and ci[0] > 0.5` while
    `evidence_sufficient = not abstain`, so evidence-sufficient is the strictly
    weaker predicate and *cannot* drop a row that would have multiplied size — it
    also leaves the rows that are one settled episode away from clearing the bar.
    Filtering on `edge_supported` would ship nothing at all on a day like
    2026-07-27, and the table would silently reappear as load-bearing later.

    Counts and reasons for everything dropped stay in the payload, so a shrinking
    table reads as evidence being thin rather than as data going missing.
    """
    if not isinstance(metrics, dict):
        return metrics
    calibration = metrics.get('hierarchical_calibration')
    if not isinstance(calibration, dict):
        return metrics
    groups = calibration.get('current_group_calibrators')
    if not isinstance(groups, list):
        return metrics

    kept = [g for g in groups if isinstance(g, dict) and g.get('evidence_sufficient')]
    omitted = [g for g in groups if g not in kept]
    reasons = {}
    for g in omitted:
        if isinstance(g, dict):
            reason = g.get('abstain_reason') or 'unspecified'
            reasons[reason] = reasons.get(reason, 0) + 1

    trimmed = dict(calibration)
    trimmed['current_group_calibrators'] = kept
    trimmed['current_group_calibrator_count'] = len(groups)
    trimmed['current_group_calibrators_omitted'] = len(omitted)
    trimmed['omitted_abstain_reasons'] = reasons
    trimmed['omitted_rule'] = (
        'Rows with evidence_sufficient=false are omitted; treat any group absent '
        'from this table as abstain (signal_size_multiplier=0), which is what both '
        'skills already require for a missing row.')
    return {**metrics, 'hierarchical_calibration': trimmed}


def compute_decision_metrics():
    """Settle the v2 ledger and return episode-level decision metrics."""
    decisions = decision_v2.load_decisions()
    # Preserve execution ground truth while migrating; prospective detection is
    # applied only to triggered decisions whose execution is still unknown.
    for d in decisions:
        if (d.get('execution') or {}).get('status') != 'unknown':
            continue
        if (d.get('evaluation') or {}).get('triggered') is not True:
            continue
        legacy_view = {
            'plan_date': d.get('plan_date'), 'ticker': d.get('ticker'),
            'bucket': d.get('action'), 'leg': d.get('leg'),
            'condition': d.get('condition') or {},
        }
        verdict = _detect_followed(legacy_view)
        if verdict in ('true', 'false'):
            d['execution'] = {'status': 'followed' if verdict == 'true' else 'not_followed',
                              'detected_at': datetime.now().isoformat(), 'source': 'git_shares_diff'}
    decision_v2.settle_decisions(decisions)
    decision_v2.write_decisions(decisions)
    return trim_abstaining_calibrators(decision_v2.compute_metrics(decisions))


def refresh_daily_bars():
    """Append newly closed sessions to `memory/bars/` before anything settles.

    The canonical bar store is what decision_v2 settles against, and settling only
    *reads* it — nothing in the ledger path ever fetches. The store was backfilled
    once (8aad505, every bar stamped 2026-07-15T23:39) and then had no writer at
    all: no cron, no contract entry, no workflow called the daily-bar writer. So each
    new session was invisible to the ledger, its decisions stayed `pending`
    forever, and the dashboard kept refreshing around a win rate that could no
    longer move. This is that writer, and it has to run ahead of [10].

    Non-fatal by design: a stale store degrades to `pending`, which is bad but
    honest — losing the whole morning brief to a provider hiccup is worse. A
    non-zero exit means the provider now disagrees with a bar the ledger already
    settled against; fetch_daily_bars never overwrites one, so that surfaces as an
    issue for a human to resolve with --repair rather than being applied here.
    """
    cmd = clawock_argv('daily-bars')
    try:
        r = subprocess.run(cmd, cwd=WS, capture_output=True, text=True, timeout=300)
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    out = (r.stdout or '') + (r.stderr or '')
    res = {'ok': r.returncode == 0, 'returncode': r.returncode}
    m = re.search(r'(\d+) bars added, (\d+) revised', out)
    if m:
        res['added'], res['revised'] = int(m.group(1)), int(m.group(2))
    if r.returncode != 0:
        res['conflicts'] = [ln.strip() for ln in out.splitlines()
                            if ' vs fetched ' in ln or 'insane OHLC' in ln][:10]
    res['stale'] = bars_staleness()
    return res


def _last_closed_session(market):
    """The newest date `market` actually traded and has since closed (17:00 local).

    Walks back through trading_calendar rather than subtracting a day: a missing bar
    is not a closed market. Conflating the two is what once deleted 10 live US rows,
    and on any Monday a naive "yesterday" would report the whole weekend as missing.
    """
    d = datetime.now(ZoneInfo(trading_calendar.MARKET_TZ[market]))
    cur = d.date() if d.hour >= 17 else d.date() - timedelta(days=1)
    for _ in range(14):  # a two-week hole is a broken store, not a holiday
        if trading_calendar.is_trading_day(market, cur):
            return cur
        cur -= timedelta(days=1)
    return None


def bars_staleness():
    """Per-leg gap between the newest stored bar and the last session that closed.

    Reported per leg, never as one number: HK and US close on different days, so a
    shared cutoff would flag one of them as stale every single morning. This is the
    check that would have caught the store going a month without a writer — the
    fetch reporting "+0 bars" looks identical to "nothing to do".

    Two levels, because they mean different things and only one is an alarm:

    * leg — the leg's newest bar vs its calendar. The whole leg falling behind means
      the writer is dead or the provider is blocked. That is the regression guard.
    * `laggards` — tickers behind their own leg, reported but never raised. A thin
      name legitimately prints no bar on a day it never traded (a freshly listed line
      may have only one bar), so flagging those would cry wolf every morning until nobody reads
      the warnings. A real per-ticker outage shows up as a laggard that keeps
      growing, which is a question for a human, not an exit code.
    """
    bars_dir = WS / 'memory' / 'bars'
    out = {}
    for leg, market in (('HK', 'hk'), ('US', 'us')):
        per_ticker = {}
        for p in bars_dir.glob('*.json'):
            try:
                doc = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if (doc.get('leg') or '') != leg or not doc.get('bars'):
                continue
            per_ticker[doc.get('ticker') or p.stem] = max(doc['bars'])
        if not per_ticker:
            continue
        newest = max(per_ticker.values())
        expected = _last_closed_session(market)
        missing = []
        # Past the holiday table's horizon `is_trading_day` has no data and answers
        # True for everything, so it would file 2027-01-01 as a missing session every
        # January until someone extends the table. Unlike `closed_reason` it does not
        # fail open. The table is extended each December by convention; until then the
        # honest report is "the calendar expired", not an invented list of holes.
        expired = bool(expected and expected.year > trading_calendar.LATEST_YEAR)
        if expected and not expired:
            cur = date.fromisoformat(newest) + timedelta(days=1)
            while cur <= expected:
                if trading_calendar.is_trading_day(market, cur):
                    missing.append(cur.isoformat())
                cur += timedelta(days=1)
        out[leg] = {'newest_bar': newest,
                    'last_closed_session': expected.isoformat() if expected else None,
                    'missing_sessions': missing,
                    'calendar_expired': expired,
                    'laggards': {t: d for t, d in sorted(per_ticker.items()) if d < newest}}
    return out


def _recent_price_moves(tickers, lookback_sessions=5):
    """Per-ticker price move over the last N closed sessions — fuels the
    'is this news already priced in?' judgement (2026-05-30). A bull market
    prices good news fast: if the stock already ran on a catalyst, acting on
    that headline is chasing. Returns {ticker: {'px_pct': float, 'n_sessions': int}}.

    Source discipline (2026-08 audit, #963): this used to string together
    `current_price` from the last few memory/snapshots/*.json files, but that
    field carries fetch vintage, not session identity — across 15 snapshots,
    00100's current_price was the previous close 7 times, that day's close 3,
    an intraday print 5 (see market_data/bars.py header). A priced-in signal
    built from it can read "already ran" or "hasn't moved" purely as an
    artefact of when each cron happened to fetch. The move now reads closes
    from the canonical bar store: session-dated, raw, completed sessions only,
    and [9] refreshes it earlier in this same preflight. A ticker the store
    does not cover gets no move at all — SKILL.md already defines a null
    recent_move as 无快照 — never a snapshot-vintage substitute."""
    want = set(tickers)
    if not want:
        return {}
    out = {}
    for tk in sorted(want):
        try:
            doc = json.loads((WS / 'memory' / 'bars' / f'{tk}.json').read_text())
            closes = [bar.get('close') for _, bar in sorted((doc.get('bars') or {}).items())]
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        closes = [c for c in closes if isinstance(c, (int, float)) and c]
        window = closes[-(lookback_sessions + 1):]
        if len(window) < 2 or not window[0]:
            continue
        out[tk] = {'px_pct': round((window[-1] / window[0] - 1) * 100, 1),
                   'n_sessions': len(window) - 1}
    return out


def load_em_news(issues):
    """Read em_news.json (Eastmoney Chinese-language info layer) → LLM-friendly subset.

    Widens the brief's information inputs where clawock is thinnest: HK-holding
    Chinese news + market 7x24 快讯. Catalyst-grade (dated, company-specific), so
    it feeds the catalyst-gate. Stale/missing → {} (warn-only, never blocks)."""
    path = WS / 'assets' / 'data' / 'em_news.json'
    if not path.exists():
        issues.append('em_news.json 缺失 — clawock em-news 未跑(中文消息源)')
        return {}
    try:
        d = json.loads(path.read_text())
        hold = {tk: {'name': v.get('name'),
                     'items': [{'date': i.get('date'), 'title': i.get('title')}
                               for i in (v.get('items') or [])[:3]]}
                for tk, v in (d.get('holdings_news') or {}).items()}
        mkt = [{'date': i.get('date'), 'title': i.get('title')}
               for i in (d.get('market_724') or [])[:5]]
        return {'holdings_news': hold, 'market_724': mkt,
                'generated_at': d.get('generated_at')}
    except Exception as e:
        issues.append(f'em_news.json 解析失败: {e}')
        return {}


def _payload_age_hours(payload):
    """Age in hours from the payload's own `generated_at`, or None if absent/unparseable.

    WHY NOT file mtime (2026-07 audit): `actions/checkout` stamps every tracked
    file with a fresh checkout time, so a committed-days-ago sidecar reads as
    seconds old. The off-host brief fallback used st_mtime and therefore fed
    stale macro/sentiment/influencer into a live trading brief while labelling it
    fresh. The producer stamps `generated_at`; that is the only honest clock.
    Callers treat None (missing/bad stamp) as STALE — an unprovable age is not a
    fresh one.
    """
    gen = (payload or {}).get('generated_at')
    if not gen:
        return None
    try:
        t = datetime.fromisoformat(str(gen).replace('Z', '+00:00'))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


# A materially future generated_at (beyond clock skew) is as untrustworthy as an
# old one — it means a broken producer clock, not fresh data.
_CLOCK_SKEW_H = 2


def _is_stale(age, cutoff_h):
    """True if age (hours, or None) is unusable: unknown, too old, or from the
    future beyond clock skew. Callers omit stale data rather than feed it."""
    return age is None or age > cutoff_h or age < -_CLOCK_SKEW_H


def _age_str(age):
    return f'{age:.0f}h' if age is not None else 'unknown-age (no generated_at)'


def load_macro_and_sentiment(today, issues):
    """Read GH-Action-produced macro.json + sentiment.json; trim to LLM-friendly subset.

    Files are written daily by sentiment-scan.yml / macro-scan.yml. Stale (>36h)
    or missing files emit a non-fatal warn — brief still runs, just without these
    sections.

    Returns: (macro_trim, sentiment_trim) — either may be {} on miss.
    """
    macro_path = WS / 'assets' / 'data' / 'macro.json'
    sent_path  = WS / 'assets' / 'data' / 'sentiment.json'
    stale_cutoff_h = 36

    macro_trim = {}
    try:
        if not macro_path.exists():
            print(f'   ⚠ macro.json missing — sentiment-scan never ran')
            issues.append('macro snapshot missing')
        else:
            m = json.loads(macro_path.read_text())
            age = _payload_age_hours(m)
            if _is_stale(age, stale_cutoff_h):
                # OMIT stale/unknown-age data — do NOT feed it as fresh, and do NOT
                # append to `issues` (main() returns exit 1 on any issue, which
                # under the fallback workflow's pipefail would hard-fail the entire
                # brief — a worse outage than a missing macro section). The brief
                # runs without macro; downstream postflight sees no macro context.
                print(f'   ⚠ macro stale/unknown ({_age_str(age)}, cutoff '
                      f'{stale_cutoff_h}h) — omitting from brief (non-fatal)')
            else:
                def _q(k):
                    v = m.get(k)
                    if not v: return None
                    return {'price': v.get('price'), 'change_pct': v.get('change_pct'),
                            'source': v.get('source')}
                macro_trim = {
                    'as_of':        m.get('generated_at'),
                    'age_hours':    round(age, 1),
                    'vix':          _q('vix'),
                    'dxy':          _q('dxy'),
                    'treasury_10y_yield_pct': (m.get('treasury_10y') or {}).get('yield_pct'),
                    'fear_greed':   m.get('fear_greed'),
                    'hsi':          _q('hsi'),
                    'hstech':       _q('hstech'),
                    'spx':          _q('spx'),
                    'nasdaq':       _q('nasdaq'),
                    'fed_press':    (m.get('fed_press') or [])[:3],
                }
                macro_trim['regime'] = _classify_regime(macro_trim)  # risk_on/neutral/risk_off
                fg = macro_trim['fear_greed'] or {}
                print(f'   macro: VIX {(macro_trim["vix"] or {}).get("price","?")}, '
                      f'F&G {fg.get("score","?")} ({fg.get("rating","?")}), '
                      f'fed_press {len(macro_trim["fed_press"])}')
    except Exception as e:
        print(f'   ⚠ macro load failed: {e}')
        issues.append(f'macro load exception: {type(e).__name__}')

    sentiment_trim = {}
    try:
        if not sent_path.exists():
            print(f'   ⚠ sentiment.json missing — sentiment-scan never ran')
            issues.append('sentiment snapshot missing')
        else:
            s = json.loads(sent_path.read_text())
            age = _payload_age_hours(s)
            if _is_stale(age, stale_cutoff_h):
                # Omit stale/unknown sentiment (non-fatal — see macro note above).
                print(f'   ⚠ sentiment stale/unknown ({_age_str(age)}, cutoff '
                      f'{stale_cutoff_h}h) — omitting from brief (non-fatal)')
            else:
                # price-in lens: recent 5-session move per signalled ticker (priced-in check)
                signalled = [t.get('ticker') for t in s.get('tickers', [])
                             if t.get('reddit_mentions_7d') or t.get('google_news_en')
                             or t.get('google_news_zh')]
                moves = _recent_price_moves(signalled)
                tickers_out = []
                for t in s.get('tickers', []):
                    reddit_n  = t.get('reddit_mentions_7d')
                    reddit_st = t.get('reddit_status') or 'ok'
                    gn_en     = t.get('google_news_en') or []
                    gn_zh     = t.get('google_news_zh') or []
                    # Skip noise: nothing measured on either source. A name whose
                    # Reddit lookup did not answer is NOT quiet — it is unknown,
                    # and dropping it here would hide the outage rather than the
                    # noise (#1237).
                    if not reddit_n and reddit_st == 'ok' and not gn_en and not gn_zh:
                        continue
                    tickers_out.append({
                        'ticker': t.get('ticker'),
                        'name':   t.get('name'),
                        'region': t.get('region'),
                        'reddit_mentions_7d': reddit_n,
                        'reddit_status': reddit_st,
                        # Title and link only: the search feed carries no score
                        # and no comment count, and defaulting them to 0 made a
                        # post nobody fetched look like a post nobody upvoted.
                        'reddit_top': [{'title': p.get('title'), 'url': p.get('url')}
                                       for p in (t.get('reddit_posts') or [])[:3]],
                        'news_top':   [n.get('title') for n in (gn_en + gn_zh)[:3] if n.get('title')],
                        'recent_move': moves.get(t.get('ticker')),  # {px_pct, n_sessions} or None — priced-in check
                    })
                sentiment_trim = {
                    'as_of':       s.get('generated_at'),
                    'age_hours':   round(age, 1),
                    'sources':     s.get('sources', []),
                    'tickers':     tickers_out,
                }
                with_signal = sum(1 for t in tickers_out if t['reddit_mentions_7d'] or t['news_top'])
                unanswered = sum(1 for t in tickers_out if t['reddit_status'] != 'ok')
                print(f'   sentiment: {with_signal}/{len(s.get("tickers",[]))} tickers '
                      f'have reddit/news signal'
                      + (f'; reddit did not answer for {unanswered}' if unanswered else ''))
    except Exception as e:
        print(f'   ⚠ sentiment load failed: {e}')
        issues.append(f'sentiment load exception: {type(e).__name__}')

    return macro_trim, sentiment_trim


def load_influencer_feed(issues):
    """Read GH-Action-produced influencer_feed.json (Trump/Musk/Serenity radar).

    Written by influencer-scan.yml before the brief. Stale (>36h)/missing → warn,
    brief still runs without the 名人异动 section. Returns trimmed dict or {}.
    """
    path = WS / 'assets' / 'data' / 'influencer_feed.json'
    try:
        if not path.exists():
            print('   ⚠ influencer_feed.json missing — influencer-scan never ran')
            issues.append('influencer feed missing')
            return {}
        d = json.loads(path.read_text())
        age = _payload_age_hours(d)
        if _is_stale(age, 36):
            # Omit stale/unknown influencer feed (non-fatal — see macro note above);
            # brief runs without the 名人异动 section rather than on stale statements.
            print(f'   ⚠ influencer feed stale/unknown ({_age_str(age)}) '
                  f'— omitting from brief (non-fatal)')
            return {}
        # Trim each item to the fields the brief needs.
        def _trim(it):
            return {k: it.get(k) for k in
                    ('author', 'stance', 'relevance', 'held', 'new_ideas',
                     'sector_holdings', 'sectors', 'summary_cn')}
        out = {
            'as_of':     d.get('generated_at'),
            'age_hours': round(age, 1),
            'counts':    d.get('counts', {}),
            'held_hits': [_trim(x) for x in d.get('held_hits', [])][:6],
            'new_ideas': [_trim(x) for x in d.get('new_ideas', [])][:6],
            'sector_hits': [_trim(x) for x in d.get('sector_hits', [])][:4],
        }
        c = out['counts']
        print(f'   influencer: {c.get("held_hits",0)} held-hits, '
              f'{c.get("new_ideas",0)} new-ideas, {c.get("sector_hits",0)} sector')
        return out
    except Exception as e:
        print(f'   ⚠ influencer feed load failed: {e}')
        issues.append(f'influencer load exception: {type(e).__name__}')
        return {}


def analyze_us():
    # [1] Refresh prices
    issues = []
    print('\n[1/14] Refresh US prices')
    us_out, us_ok = _run_clawock('analyze-us', ['--no-news'])
    if not us_ok:
        issues.append(f'US refresh failed: {us_out[-200:]}')
        print(f'   ⚠️  {issues[-1]}')
    else:
        print('   ✓ done')
    return None, issues


def analyze_hk():
    issues = []
    print('[2/14] Refresh HK prices')
    hk_out, hk_ok = _run_clawock('analyze-hk', ['--no-news'])
    if not hk_ok:
        issues.append(f'HK refresh failed: {hk_out[-200:]}')
        print(f'   ⚠️  {issues[-1]}')
    else:
        print('   ✓ done')
    return None, issues


def fx_rate():
    # [3] FX
    issues = []
    print('[3/14] FX rate')
    fx = fetch_fx_rate()
    if 'error' in fx:
        issues.append(f'FX fallback used: {fx["error"][-200:]}')
    print(f'   USDHKD = {fx["rate"]}  ({fx["source"]})')
    return fx, issues


def _node_filings(portfolio):
    # [6] SEC EDGAR
    issues = []
    print('[6/14] SEC EDGAR US singles')
    us_fund = collect_us_fundamentals(portfolio)
    for t, data in us_fund.items():
        if 'error' in data:
            print(f'   ⚠️  {t}: {data["error"][:80]}')
            issues.append(f'SEC EDGAR {t} failed')
        else:
            kf = data.get('key_financials', {})
            print(f'   ✓ {t}: {len(kf)} concepts')
    return us_fund, issues


def peer_scan_node(portfolio):
    # [8] Peer scan — for each active holding, fetch peer prices + flag divergence
    issues = []
    print('[8/14] Peer scan')
    peer_scan = collect_peer_scan(portfolio)
    print(f'   {len(peer_scan)} holdings with peer data; {sum(1 for h in peer_scan.values() if h.get("divergence_signal"))} divergence signals')
    return peer_scan, issues


def daily_bars_node():
    # [9] Canonical bars — must precede [10]: settling only reads this store.
    issues = []
    print('[9/14] Refresh canonical daily bars')
    bars = refresh_daily_bars()
    if not bars.get('ok'):
        if bars.get('conflicts'):
            # Stored bars the ledger already settled against now disagree with the
            # provider. Never auto-applied — see `clawock daily-bars --repair`.
            print(f'   ⚠ {len(bars["conflicts"])} provider conflicts, nothing overwritten:')
            for c in bars['conflicts'][:5]:
                print(f'     {c}')
            issues.append(f'{len(bars["conflicts"])} bar conflicts need --repair')
        else:
            print(f'   ⚠ bar refresh failed: {bars.get("error", "")[:150]}')
            issues.append('daily bar refresh failed')
    else:
        print(f'   +{bars.get("added", 0)} bars, {bars.get("revised", 0)} revised')
    for leg, st in (bars.get('stale') or {}).items():
        miss = st.get('missing_sessions') or []
        if st.get('calendar_expired'):
            # Actionable and specific: the check is blind, rather than quietly
            # inventing a holiday-shaped hole every January.
            print(f'   ⚠ {leg}: trading calendar table ends at '
                  f'{trading_calendar.LATEST_YEAR}; freshness unverifiable')
            issues.append(f'trading_calendar table expired past '
                          f'{trading_calendar.LATEST_YEAR} — extend it; {leg} bar '
                          f'freshness cannot be checked')
        elif miss:
            # "+0 bars" and "the store has no writer" print identically; only the
            # calendar tells them apart, so an unfetched session is an issue here.
            print(f'   ⚠ {leg}: newest bar {st["newest_bar"]}, last close '
                  f'{st["last_closed_session"]} — {len(miss)} session(s) missing: {miss}')
            issues.append(f'{leg} bars missing {len(miss)} session(s); '
                          f'those decisions cannot settle')
        else:
            print(f'   ✓ {leg}: current through {st["newest_bar"]}')
        if st.get('laggards'):
            # Informational: thin names skip sessions legitimately. See bars_staleness.
            print(f'     {leg} behind leg: '
                  + ', '.join(f'{t}@{d}' for t, d in st['laggards'].items()))
    return None, issues


def portfolio_risk_node():
    # [10] Risk metrics — Tier 2: β / vol / DD / Sharpe / margin sim
    issues = []
    print('[11/14] Risk metrics')
    risk = {}
    try:
        r = subprocess.run(clawock_argv('portfolio-risk'), cwd=WS,
                           capture_output=True, text=True, timeout=180, check=False)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or '')[-500:]
            print(f'   ⚠ risk metrics exited {r.returncode}: ...{tail}')
        risk_path = WS / 'assets' / 'data' / 'risk.json'
        if risk_path.exists():
            risk = json.loads(risk_path.read_text())
            # Freshness check — silent failures can leave a stale file in place
            from datetime import datetime as _dt, timezone as _tz
            gen = risk.get('generated_at', '')
            try:
                age_h = (_dt.now(_tz.utc) - _dt.fromisoformat(gen.replace('Z','+00:00'))).total_seconds() / 3600
                if age_h > 26:  # daily refresh; >1 day = stale
                    print(f'   ⚠ risk.json stale: generated_at={gen} ({age_h:.0f}h ago)')
            except Exception:
                pass
            alerts = risk.get('alerts', [])
            print(f'   US β={risk.get("us",{}).get("beta_spx","?")}, combined vol={risk.get("combined",{}).get("vol_30d_annualized","?")}, alerts={len(alerts)}')
            for a in alerts[:5]:
                print(f'   ⚠ {a["type"]:18s} ({a["severity"]:6s}) {a["detail"][:80]}')
    except Exception as e:
        print(f'   ⚠ risk metrics failed: {e}')
    return risk, issues


def regime_node():
    # [10b] Leverage dial — HSTECH 200DMA trend + 20d vol → leveraged-ETF cap multiplier
    issues = []
    lev_regime = None
    try:
        subprocess.run(clawock_argv('regime'),
                       capture_output=True, text=True, timeout=60, check=False)
        lr_path = WS / 'assets' / 'data' / 'lev_regime.json'
        if lr_path.exists():
            lev_regime = json.loads(lr_path.read_text())
            print(f'   🧭 lev_regime: {lev_regime.get("tier")} (×{lev_regime.get("lev_cap_mult")}) — {lev_regime.get("label","")}')
    except Exception as e:
        print(f'   ⚠ lev_regime compute failed: {e}')
    return lev_regime, issues


def quant_node():
    # [10b2] 量化因子层 — 趋势/动量/RSI/z-score/ATR吊灯止损/vol-target（纯算术，
    # LLM 技术面判断只准引用此表）。merge-not-overwrite，单只抓空保留旧值。
    issues = []
    quant_signals = {}
    try:
        subprocess.run(clawock_argv('quant'),
                       capture_output=True, text=True, timeout=120, check=False)
        qs_path = WS / 'assets' / 'data' / 'quant_signals.json'
        if qs_path.exists():
            quant_signals = json.loads(qs_path.read_text())
            tags = {k: v.get('tag') for k, v in (quant_signals.get('rows') or {}).items()
                    if v.get('status') in (None, 'fresh')}
            nonfresh = [k for k, v in (quant_signals.get('rows') or {}).items()
                        if v.get('status') not in (None, 'fresh')]
            print(f'   📊 quant_signals: {len(tags)} fresh symbols'
                  f' / {len(nonfresh)} unavailable — '
                  + '; '.join(f'{k}:{v}' for k, v in list(tags.items())[:4]) + ' …')
    except Exception as e:
        print(f'   ⚠ quant_signals compute failed: {e}')
    return quant_signals, issues


def quant_review_node():
    # [10b3] 因子 edge 自检 — 历史留痕 vs forward return 对账（自迭代：MIN_N=20
    # 样本闸 + 聚类 CI 越线才解锁，#934 与 t0_setup_review 同纪律；反向只展示
    # 不入决策）。纯本地文件运算。
    issues = []
    quant_review = {}
    try:
        subprocess.run(clawock_argv('quant-review'),
                       capture_output=True, text=True, timeout=60, check=False)
        qr_path = WS / 'assets' / 'data' / 'quant_signal_review.json'
        if qr_path.exists():
            quant_review = json.loads(qr_path.read_text())
            print(f'   📐 factor edge: {quant_review.get("summary", "")[:80]}')
    except Exception as e:
        print(f'   ⚠ quant_signal_review failed: {e}')
    return quant_review, issues


def cross_factor_node(portfolio):
    # [10b3b] Cross-sectional factor research — curated peers + 1x underlyings,
    # sector-neutral ranks and strictly prospective activation. The full artifact
    # stays on disk; context gets a compact view to avoid spending brief tokens on
    # 38 complete research rows. `usable_for_decisions=false` is a hard boundary.
    issues = []
    cross_sectional_factor = {}
    cross_sectional_factor_ctx = {}
    try:
        subprocess.run(
            clawock_argv('cross-factor'),
            capture_output=True, text=True, timeout=240, check=False,
        )
        cs_path = WS / 'assets' / 'data' / 'cross_sectional_factor.json'
        if cs_path.exists():
            cross_sectional_factor = json.loads(cs_path.read_text())
            activation = cross_sectional_factor.get('activation') or {}
            rankings = cross_sectional_factor.get('live_rankings') or {}
            held = {
                h.get('ticker')
                for book in portfolio.get('portfolios', {}).values()
                for h in book.get('holdings', [])
                if h.get('shares', 0) > 0
            }
            signal_names = {
                str((get_instrument(ticker) or {}).get('signal_symbol') or '')
                for ticker in held
            }
            held_rows = {
                ticker: row for ticker, row in rankings.items()
                if ticker in held or ticker in signal_names
            }
            leaders = sorted(
                rankings.items(),
                key=lambda item: item[1].get('composite_score') or -999,
                reverse=True,
            )[:8]
            cross_sectional_factor_ctx = {
                'as_of': cross_sectional_factor.get('as_of'),
                'activation': activation,
                'validation': cross_sectional_factor.get('validation'),
                'held_rankings': held_rows,
                'sector_leaders': dict(leaders),
                'leveraged_proxy_decay': cross_sectional_factor.get(
                    'leveraged_proxy_decay'
                ),
            }
            print(
                f'   🧪 cross-sectional: active={activation.get("active", False)}, '
                f'blockers={",".join(activation.get("blockers") or [])}'
            )
    except Exception as e:
        print(f'   ⚠ cross-sectional factor failed: {e}')
    return cross_sectional_factor_ctx, issues


def evidence_node():
    # 证据页：读上面刚刷新的产物重新生成，保证「测了什么、什么没通过」不落后于事实。
    issues = []
    try:
        subprocess.run(clawock_argv('evidence'),
                       capture_output=True, text=True, timeout=60, check=False)
    except Exception as e:
        print(f'   ⚠ evidence page rebuild failed: {e}')
    return None, issues


def peer_residual_node(portfolio):
    # [10b3c] Curated peer residual/leadership research. HK taxonomy is explicitly
    # manual-only; leveraged products are folded to 1x before basket construction.
    # As with the broader cross-sectional layer, inactive rules are display-only.
    issues = []
    peer_residual_ctx = {}
    try:
        subprocess.run(
            clawock_argv('peer-residual'),
            capture_output=True, text=True, timeout=180, check=False,
        )
        pr_path = WS / 'assets' / 'data' / 'peer_residual.json'
        if pr_path.exists():
            peer_residual = json.loads(pr_path.read_text())
            peer_live = peer_residual.get('live') or {}
            held = {
                h.get('ticker')
                for book in portfolio.get('portfolios', {}).values()
                for h in book.get('holdings', [])
                if h.get('shares', 0) > 0
            }
            signal_names = {
                str((get_instrument(ticker) or {}).get('signal_symbol') or '')
                for ticker in held
            }
            peer_residual_ctx = {
                'as_of': peer_residual.get('as_of'),
                'taxonomy': peer_residual.get('taxonomy'),
                'calibration': peer_residual.get('calibration'),
                'rule_activation': peer_residual.get('rule_activation'),
                'held': {
                    ticker: row for ticker, row in peer_live.items()
                    if ticker in held or ticker in signal_names
                },
            }
            active_peer_rules = [
                rule for rule, state in
                (peer_residual.get('rule_activation') or {}).items()
                if state.get('active')
            ]
            print(
                f'   🧭 peer residual: active_rules='
                f'{",".join(active_peer_rules) or "none"}, HK_auto=false'
            )
    except Exception as e:
        print(f'   ⚠ peer residual engine failed: {e}')
    return peer_residual_ctx, issues


def t0_node():
    # [10b4] T+0 牌面评级 — 零额外请求（从已抓字段 + quant ATR 推导），追高检测。
    # 紧跟 quant_signals 之后跑（依赖其 ATR 刷新）。
    issues = []
    t0_setups = {}
    try:
        subprocess.run(clawock_argv('t0'),
                       capture_output=True, text=True, timeout=60, check=False)
        t0_path = WS / 'assets' / 'data' / 't0_setups.json'
        if t0_path.exists():
            t0_setups = json.loads(t0_path.read_text())
            chase = [k for k, v in (t0_setups.get('rows') or {}).items() if v.get('grade') == '🔴']
            print(f'   🎯 T+0 牌面: {len(t0_setups.get("rows", {}))} 票'
                  + (f' — 🔴 追高: {", ".join(chase)}' if chase else ''))
    except Exception as e:
        print(f'   ⚠ t0_setups compute failed: {e}')
    return t0_setups, issues


def t0_review_node():
    # [10b4b] T+0 牌面 edge 自检 — 牌面评级对账 T+1 forward return（数据背书）。
    # 零网络：结算用历史留痕的 close，绝不每分钟抓价。
    issues = []
    t0_review = {}
    try:
        subprocess.run(clawock_argv('t0-review'),
                       capture_output=True, text=True, timeout=60, check=False)
        tr_path = WS / 'assets' / 'data' / 't0_setup_review.json'
        if tr_path.exists():
            t0_review = json.loads(tr_path.read_text())
            print(f'   🎯 T+0 牌面背书: {t0_review.get("summary", "")[:80]}')
    except Exception as e:
        print(f'   ⚠ t0_setup_review failed: {e}')
    return t0_review, issues


def em_news_node():
    # [10b6] 中文消息源 — Eastmoney HK 持仓新闻 + 7x24 快讯（信息广度，喂 catalyst-gate）。
    # 借鉴 UZI-Skill 的数据源广度；信息收集是 LLM 强项 + kcn token 充足。失败 fail-soft。
    issues = []
    try:
        subprocess.run(clawock_argv('em-news'), cwd=WS,
                       capture_output=True, text=True, timeout=60, check=False)
    except Exception as e:
        print(f'   ⚠ clawock em-news failed: {e}')
    return None, issues


def catalysts_node():
    # [11] Catalyst calendar — next 14d earnings + FOMC + macro
    issues = []
    catalysts = {}
    try:
        result = subprocess.run(
            clawock_argv('catalysts', '--json'), cwd=WS,
            capture_output=True, text=True, timeout=60)
        cat_out, cat_ok = result.stdout, result.returncode == 0
        if not cat_ok:
            print(f'   ⚠ catalysts fetch failed: {cat_out[-150:]}')
            issues.append('catalysts fetch failed')
        else:
            catalysts = json.loads(cat_out)
            summary = catalysts.get('summary', {})
            print(f'   earnings: {summary.get("earnings_count", 0)}, '
                  f'FOMC: {summary.get("fomc_in_window", 0)}, '
                  f'macro: {summary.get("macro_count", 0)}')
            hi = summary.get('highest_impact_within_7d')
            if hi:
                print(f'   highest impact 7d: {hi}')
            if 'error' in catalysts:
                print(f'   ⚠ partial errors: {list(catalysts["error"].keys())}')
    except Exception as e:
        print(f'   ⚠ catalysts step failed: {e}')
        issues.append(f'catalysts step exception: {type(e).__name__}')
    return catalysts, issues


def news_evidence_node():
    # [11b] News evidence graph — normalize filings/news/calendar nodes, expire
    # repeated summaries and apply deterministic source/novelty/confirmation
    # gates. Only a compact decision envelope enters the LLM context.
    issues = []
    news_evidence_ctx = {}
    try:
        graph_run = subprocess.run(
            clawock_argv('news-evidence'), capture_output=True, text=True,
            timeout=150, check=False,
        )
        graph_out = (graph_run.stdout or '') + (graph_run.stderr or '')
        graph_ok = graph_run.returncode == 0
        graph_path = WS / 'assets' / 'data' / 'news_evidence_graph.json'
        if not graph_ok:
            print(f'   ⚠ news evidence graph failed: {graph_out[-150:]}')
            issues.append('news evidence graph failed')
        elif graph_path.exists():
            graph = json.loads(graph_path.read_text())
            current_events = [
                event for event in graph.get('events') or []
                if event.get('status') in ('active', 'upcoming')
            ]
            current_events.sort(
                key=lambda event: (
                    bool(event.get('actionable_escalation')),
                    bool(event.get('high_impact')),
                    event.get('source_reliability') or 0,
                    event.get('publication_time', {}).get('iso') or '',
                ),
                reverse=True,
            )
            decision_fields = (
                'event_id', 'ticker', 'reported_ticker', 'event_type',
                'title', 'publication_time', 'event_time', 'source_type',
                'source_reliability', 'novelty_score', 'novelty_reason',
                'status', 'expires_at', 'impact_direction', 'confirmation',
                'high_impact', 'actionable_escalation',
                'actionable_blockers', 'decision_permission',
            )
            news_evidence_ctx = {
                'as_of': graph.get('as_of'),
                'summary': graph.get('summary'),
                'events': [
                    {key: event.get(key) for key in decision_fields}
                    for event in current_events[:40]
                ],
                'actionable_events': graph.get('actionable_events') or [],
                'information_overlay': graph.get('information_overlay') or {},
                'tavily_resolution_queue': (
                    graph.get('tavily_resolution_queue') or []
                ),
                'policy': graph.get('policy'),
            }
            summary = graph.get('summary') or {}
            print(
                f'   🧾 news evidence: {summary.get("events", 0)} events, '
                f'{summary.get("actionable_escalations", 0)} actionable, '
                f'{summary.get("tavily_resolution_queue", 0)} unresolved'
            )
    except Exception as e:
        print(f'   ⚠ news evidence graph step failed: {e}')
        issues.append(
            f'news evidence graph exception: {type(e).__name__}'
        )
    return news_evidence_ctx, issues


def benchmark_node():
    # Benchmark history (SPY + HSI/HSTECH) for the Equity Curve overlay.
    # Refreshed once per day at brief time; consumed by build_dashboard.
    issues = []
    print('[13/14] Fetch benchmark history')
    try:
        bm_out, bm_ok = _run_clawock('benchmark', timeout=30)
        if not bm_ok:
            print(f'   ⚠ benchmark fetch failed: {bm_out[-150:]}')
            issues.append('benchmark history fetch failed')
        else:
            # Surface a one-line summary
            tail = bm_out.strip().splitlines()[-1] if bm_out.strip() else ''
            print(f'   {tail}')
    except Exception as e:
        print(f'   ⚠ benchmark step failed: {e}')
        issues.append(f'benchmark step exception: {type(e).__name__}')
    return None, issues


NODE_ORDER = [
    # Every spawn node in today's textual execution order (#916). After each
    # wave joins, the parent extends `issues` from the wave's results in this
    # order — so an identical failure set produces a byte-identical
    # context['issues'] (and therefore generation_id) regardless of thread
    # completion order.
    # Order follows actual wave-append sequence (#941 + J-P1-1): news-evidence
    # joined WAVE3 so it never races cross-factor's rewrite of its input file.
    'analyze_us', 'analyze_hk', 'fx_rate', '_node_filings',
    'peer_scan_node', 'daily_bars_node', 'portfolio_risk_node',
    'regime_node', 'quant_node', 'quant_review_node',
    'cross_factor_node', 'evidence_node', 'peer_residual_node',
    't0_node', 't0_review_node', 'em_news_node',
    'catalysts_node', 'benchmark_node', 'news_evidence_node',
]


def _timed(fn):
    """Run one node callable; return (payload, issues, wall_s).

    Timing only — deliberately no try/except here: every node keeps its own
    original except branch and timeout cap verbatim, and a wrapper handler
    would change per-node failure semantics (#916)."""
    started = time.monotonic()
    payload, node_issues = fn()
    return payload, node_issues, time.monotonic() - started


def _run_wave(nodes, *, max_workers=2):
    """Run one DAG wave of subprocess nodes concurrently.

    nodes maps a NODE_ORDER name to a zero-arg callable returning
    (payload, issues); returns {name: (payload, issues, wall_s)}. Process
    isolation is unchanged — still one clawock subprocess per node; only the
    scheduling is concurrent, capped at max_workers=2 for the 2C/2GB box (#916).
    """
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending = {pool.submit(_timed, fn): name for name, fn in nodes.items()}
        for future in concurrent.futures.as_completed(pending):
            results[pending[future]] = future.result()
    return results


def main(argv=None):
    # This script took no arguments at all, so `--help` was not "unsupported" —
    # it was ignored, and the full preflight ran: live price fetches, SEC EDGAR,
    # Tavily. A probe meant to cost nothing did a minutes-long real run.
    #
    # CI wraps this call in `|| true`, which reads like the case was handled. It
    # is not: `|| true` catches a non-zero exit, and this never exited non-zero —
    # it hung. On 2026-08-06 that consumed the validate job's entire 10-minute
    # budget and failed a PR that had nothing to do with it.
    #
    # Parsing argv also restores the contract the repo relies on when an agent
    # probes a script: `--help` exits 0 having done nothing, and an unknown flag
    # exits 2 rather than being silently ignored — the latter is what turns
    # "mistyped argument plus valid input" into a successful-looking no-op.
    argparse.ArgumentParser(
        description=(
            "Deterministic data collection for the daily-deep-brief harness. "
            "Takes no arguments; the date comes from TODAY or HKT now()."
        ),
    ).parse_args(argv)

    # Date in HKT (the system's canonical TZ), or honor the TODAY env that the
    # brief-fallback workflow exports — so the context filename here always matches
    # the date the fallback script reads. Naive now() = runner UTC, which mismatched
    # HKT in the 16:00–23:59 UTC window and broke off-schedule fallback runs.
    today = (os.environ.get('TODAY')
             or datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d'))
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    issues = []
    job_name = '盘前深度简报'
    slot = workflow_outcomes.slot_for_job(job_name)
    workflow_outcomes.record_stage(job_name, 'preflight', 'pending', slot=slot)

    # Holiday/weekend gate: the brief covers both markets, so skip ONLY when both
    # HK and US are closed (still runs if either trades). At 08:00 HKT the relevant
    # US session is the just-closed NY day, which trading_calendar reads correctly
    # (NY-local date is still the prior calendar day at that hour).
    hk_closed = trading_calendar.closed_reason('hk')
    us_closed = trading_calendar.closed_reason('us')
    if hk_closed and us_closed:
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'skipped', slot=slot,
            reason=f'港股{hk_closed}+美股{us_closed}',
        )
        result = {'status': 'market_closed', 'date': today,
                  'reason': f'港股{hk_closed}+美股{us_closed}', 'skip': True}
        (TMP_DIR / f'brief-context-{today}.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2))
        print(f'=== MARKET CLOSED — 港股{hk_closed} + 美股{us_closed} ({today}) ===')
        print('SKIP：两市均休市，不生成简报、不调用 send/postflight，本回合结束。')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f'═════ brief_preflight.py | {today} ═════')

    step_timings = {}

    def _join(results):
        """Merge one wave into `issues`/`step_timings`; return {name: payload}.

        Issue strings are appended by the parent AFTER the wave join, in
        NODE_ORDER (= today's textual order), so an identical failure set
        yields a byte-identical context['issues'] — and therefore generation_id
        — regardless of thread completion order (#916)."""
        payloads = {}
        for name in NODE_ORDER:
            if name not in results:
                continue
            payload, node_issues, wall_s = results[name]
            issues.extend(node_issues)
            step_timings[name] = {'ok': not node_issues, 'wall_s': wall_s}
            payloads[name] = payload
        return payloads

    def _run_serial(name, fn):
        """Serial-prefix node: identical accounting to waved nodes."""
        return _join({name: _timed(fn)})[name]

    # [1]+[2] Price refreshes are STRICTLY SERIAL, never parallel: analyze-us
    # then analyze-hk each read-modify-write the SAME portfolio.json
    # (us_analysis.update_us_portfolio writes it; hk_analysis writes the same
    # path), so concurrent execution would lose one side's update (#916 §1.2).
    _run_serial('analyze_us', analyze_us)
    _run_serial('analyze_hk', analyze_hk)

    # [4] Snapshot
    print('[4/14] Portfolio snapshot')
    portfolio_path = WS / 'portfolio.json'
    snapshot_path  = SNAPSHOT_DIR / f'{today}.json'
    snapshot_path.write_bytes(portfolio_path.read_bytes())
    print(f'   ✓ {snapshot_path.name}')

    # Roll cold snapshots into _archive/ (#1040): readers look at ≤90 entries,
    # storage was unbounded. Runs HERE and only here — this postflight commits
    # with a directory-scoped `git add memory/` that carries the moves; the
    # intraday/report postflights stage explicit paths and would strand them.
    try:
        rolled = history_store.roll_dated_files(SNAPSHOT_DIR, today=today)
        if rolled:
            print(f'   ✓ archived {len(rolled)} cold snapshot(s)')
    except Exception as exc:  # non-fatal: rolling must never kill the brief
        print(f'   ! snapshot roll skipped: {exc}')

    # Load for downstream
    portfolio = json.loads(portfolio_path.read_text())

    # [5] Concentration
    print('[5/14] Concentration')
    hk_conc = compute_concentration(portfolio['portfolios']['hk_stocks']['holdings'])
    us_conc = compute_concentration(portfolio['portfolios']['us_stocks']['holdings'])
    lookthrough = compute_lookthrough_exposure(portfolio)
    print(f'   HK: HHI={hk_conc.get("hhi"):.3f} {hk_conc.get("verdict")} '
          f'(Top2 {hk_conc.get("top2_pct")}%)')
    print(f'   US: HHI={us_conc.get("hhi"):.3f} {us_conc.get("verdict")} '
          f'(Top2 {us_conc.get("top2_pct")}%)')
    print(f'   Look-through: HK factor HHI={lookthrough["hk"]["factor_hhi"]:.3f}; '
          f'US factor HHI={lookthrough["us"]["factor_hhi"]:.3f}')

    # [6] SEC EDGAR — strictly serial loop inside collect_us_fundamentals: the
    # SEC rate limiter is an in-process global, so parallel spawns would clone
    # N copies of it (#916 §1.4).
    us_fund = _run_serial('_node_filings', lambda: _node_filings(portfolio))

    # [7] Retrospective — only the plan lookup happens here. The scoring moved
    # below the settle step (#964): the verdicts are the ledger's now, and the
    # ledger is not settled against today's bars until [10].
    prior_plan = find_prior_plan(today)

    # [8]-[13] DAG waves (#916 §1.2/§1.3): serial prefix done, now three
    # concurrent waves separated by barriers, each capped at max_workers=2.
    # Wave membership carries every true dependency edge:
    #   WAVE1 — inputs are self-sufficient (fx, peers, bars, risk, regime,
    #           quant, em-news, catalysts, peer-residual); write targets are
    #           pairwise disjoint.
    #   barrier
    #   WAVE2 — quant-review/cross-factor/t0 read quant's outputs from WAVE1;
    #           news-evidence builds its graph from the em-news + catalysts
    #           artifacts finished at the barrier; benchmark STARTS only after
    #           regime FINISHED at the barrier — regime must read YESTERDAY'S
    #           benchmark.json while the benchmark node rewrites that same
    #           file, so this ordering is a byte-determinism constraint, not a
    #           data dependency (#916 §1.2).
    #   barrier
    #   WAVE3 — t0-review reconciles t0's history jsonl from WAVE2; evidence
    #           rebuilds the page from the quant-review + cross-factor
    #           artifacts finalized at the barrier.
    w1 = _join(_run_wave({
        'fx_rate': fx_rate,
        'peer_scan_node': lambda: peer_scan_node(portfolio),
        'daily_bars_node': daily_bars_node,
        'portfolio_risk_node': portfolio_risk_node,
        'regime_node': regime_node,
        'quant_node': quant_node,
        'em_news_node': em_news_node,
        'catalysts_node': catalysts_node,
        'peer_residual_node': lambda: peer_residual_node(portfolio),
    }))
    fx = w1['fx_rate']
    peer_scan = w1['peer_scan_node']
    risk = w1['portfolio_risk_node']
    lev_regime = w1['regime_node']
    quant_signals = w1['quant_node']
    catalysts = w1['catalysts_node']
    peer_residual_ctx = w1['peer_residual_node']

    # Book totals (FX-aware) — moved here from the old [5] block: fx now
    # completes in WAVE1 and rate is its only input (pure arithmetic; nothing
    # between the prefix and this point consumes it).
    rate = fx['rate']
    hk_pnl_hkd = portfolio['portfolios']['hk_stocks'].get('total_pnl', 0)
    us_pnl_usd = portfolio['portfolios']['us_stocks'].get('total_pnl', 0)
    book = {
        'hk_pnl_hkd':      round(hk_pnl_hkd, 2),
        'us_pnl_usd':      round(us_pnl_usd, 2),
        'usd_base_total':  round(hk_pnl_hkd / rate + us_pnl_usd, 2),
        'hkd_base_total':  round(hk_pnl_hkd + us_pnl_usd * rate, 2),
        'fx_used':         rate,
    }

    # news-evidence sits in WAVE3, not WAVE2: it reads
    # cross_sectional_factor.json for its confirmation gate (J-P1-1), which
    # cross-factor rewrites atomically in WAVE2 — same-wave scheduling would
    # silently feed yesterday's factors when news-evidence reached its read
    # first. em-news/catalysts inputs were satisfied at the WAVE1 barrier.
    w2 = _join(_run_wave({
        'quant_review_node': quant_review_node,
        'cross_factor_node': lambda: cross_factor_node(portfolio),
        't0_node': t0_node,
        'benchmark_node': benchmark_node,
    }))
    quant_review = w2['quant_review_node']
    cross_sectional_factor_ctx = w2['cross_factor_node']
    t0_setups = w2['t0_node']

    w3 = _join(_run_wave({
        't0_review_node': t0_review_node,
        'evidence_node': evidence_node,
        'news_evidence_node': news_evidence_node,
    }))
    t0_review = w3['t0_review_node']
    news_evidence_ctx = w3['news_evidence_node']

    # [10] V2 episode metrics — triggered-only, strategy-aware, cluster-bootstrap.
    # Settle runs only AFTER daily-bars finished at the WAVE1 barrier: settling
    # reads the canonical bar store and never fetches (#916 §1.2).
    print('[10/14] Decision metrics v2')
    decision_metrics = compute_decision_metrics()
    # Brier is never printed bare: alone it reads as "0.295, close enough to 0".
    # It only means something against the constant-forecast baseline it has to beat.
    print(f'   {decision_metrics.get("settled_episodes", 0)} settled episodes / '
          f'{decision_metrics.get("raw_decisions", 0)} raw decisions; '
          f'Brier={decision_metrics.get("brier")} vs constant-forecast baseline '
          f'{decision_metrics.get("brier_baseline_loo")} '
          f'({"beats" if decision_metrics.get("brier_beats_baseline") else "LOSES to"} it)')
    hierarchical = decision_metrics.get('hierarchical_calibration') or {}
    prequential = hierarchical.get('after_warmup') or {}
    print(f'   hierarchical prequential: n={prequential.get("n", 0)} '
          f'Brier={prequential.get("calibrated_brier")} vs raw '
          f'{prequential.get("raw_brier")}; '
          f'{hierarchical.get("abstained_predictions", 0)} historical abstentions / '
          f'{hierarchical.get("edge_supported_predictions", 0)} edge-supported')
    active_v2 = decision_metrics.get('active') or {}
    print(f'   active: n={active_v2.get("n_episodes", 0)} '
          f'avg benefit={active_v2.get("avg_benefit_pct")}%, '
          f'cluster CI={active_v2.get("cluster_ci95")}')

    # [7b] Retrospective — deliberately after [10]. It reads the settled ledger
    # (which reads canonical bars) instead of scoring yesterday's plan against
    # the portfolio snapshot, so there is one verdict per decision rather than
    # two contradictory ones in the same context bundle (#964).
    print('[7b/14] Retrospective')
    retro = compute_retrospective(prior_plan, portfolio, decision_v2.load_decisions())
    if retro.get('prior_plan_date'):
        actions = retro['decisions']
        fired = sum(1 for a in actions if a.get('trigger_fired') is True)
        not_fired = sum(1 for a in actions if a.get('trigger_fired') is False)
        ambiguous = sum(1 for a in actions if a.get('trigger_fired') is None)
        print(f'   prior plan: {retro["prior_plan_date"]} (verdicts from the v2 ledger)')
        print(f'   fired: {fired}   not fired: {not_fired}   unsettled/ambiguous: {ambiguous}')
        print(f'   conf cal: 80%+ {retro["confidence_calibration"]["conf_80_100"]}, '
              f'60-79% {retro["confidence_calibration"]["conf_60_79"]}')
    else:
        print('   first run (no prior plan)')

    # [9b] Reflection memory — per held ticker, prior call outcomes (TradingAgents-style)
    reflections = compute_reflections(portfolio)
    if reflections:
        print(f'[9b/11] Reflections: {len(reflections)} held tickers with prior-call history')

    # [10b5] 数据体检闸 — 把历史踩过的数字 bug 固化成自动门。warn-only 注入 context
    # （遵 feedback_no_individual_cron_alerts 不推送），ERROR 由 build_status 健康卡暴露。
    integrity = {}
    try:
        from clawock.portfolio import integrity as _pi
        integrity = _pi.check()
        if not integrity['ok']:
            print(f'   🔴 数据体检 {integrity["error_count"]} ERROR：')
            for f in integrity['findings']:
                if f['level'] == 'ERROR':
                    print(f'      • {f["code"]}: {f["msg"][:90]}')
        elif integrity['warn_count']:
            print(f'   🟡 数据体检 {integrity["warn_count"]} WARN（见 integrity_report.json）')
        else:
            print('   ✅ 数据体检全过')
        # 报价来源台账（#1116）：主源没覆盖满时说一句「今天这本账是谁定的价」。
        # 不是告警（全本走 fallback 是常态，见 integrity 的 quote_sources 注释），
        # 但它此前只存在于某次 cron 的 stdout 里，等于不存在。
        for _region, _row in (integrity.get('quote_sources') or {}).items():
            if _row['primary_priced'] < _row['active']:
                _others = ', '.join(
                    f'{src}×{len(ts)}' for src, ts in _row['by_source'].items())
                print(f'   ℹ️ {_region} 报价 {_row["primary_priced"]}/{_row["active"]} '
                      f'来自主源 {_row["primary"]}（{_others}）')
    except Exception as e:
        print(f'   ⚠ integrity check failed: {e}')

    # [10c] Risk guardrails — position-sizing / leverage hard caps → trim/cut directives
    guardrail = compute_risk_guardrail(
        portfolio['portfolios']['hk_stocks']['holdings'],
        portfolio['portfolios']['us_stocks']['holdings'],
        hk_conc, us_conc, risk, lev_regime=lev_regime)
    guardrail = risk_discipline.attach_breach_ids(guardrail)
    _append_guardrail_history(today, guardrail, hk_conc, us_conc, risk)
    discipline = {}
    try:
        discipline = risk_discipline.reconcile_guardrail(
            guardrail, portfolio)
    except Exception as e:
        discipline = {'error': f'{type(e).__name__}: {e}', 'records': []}
        issues.append(f'risk discipline reconcile failed: {type(e).__name__}')
    print(f'   guardrail: {guardrail["breach_count"]} breaches/stops — {guardrail["directive"][:64]}')
    if discipline.get('error'):
        print(f'   🔴 durable risk ledger failed: {discipline["error"]}')
    else:
        print(f'   durable risk ledger: {discipline.get("open_count", 0)} open / '
              f'{discipline.get("overridden_count", 0)} overridden / '
              f'oldest {discipline.get("oldest_open_days", 0)}d')
    for b in guardrail['breaches']:
        print(f'   ⛔ {b["type"]:20s} ({b["severity"]:6s}) {b["detail"][:78]}')
    for s in guardrail['hard_stop_watch']:
        print(f'   🛑 {s["detail"][:78]}')

    # [10d] 解套数学 — 纯算术回本表（浮亏持仓回本所需涨幅 / 2x 横盘 decay 成本）
    breakeven = compute_breakeven_math(
        portfolio['portfolios']['hk_stocks']['holdings'],
        portfolio['portfolios']['us_stocks']['holdings'], lev_regime=lev_regime)
    print(f'   breakeven: {len(breakeven["rows"])} 只浮亏持仓入表')

    # [13] Macro + sentiment snapshots — written by GH Action (macro-scan / sentiment-scan).
    # Read-only here; brief LLM consumes the trimmed subset so "▎大盘速读" and
    # "▎社交舆情速读" sections aren't flying blind.
    print('[14/14] Load macro + sentiment + influencer snapshots')
    macro_trim, sentiment_trim = load_macro_and_sentiment(today, issues)
    influencer_trim = load_influencer_feed(issues)
    em_news_trim = load_em_news(issues)
    # [15] Non-held AI watch list (智谱/迅策 等) — 只扫描机会,绝不产生 add 授权 (#556).
    watch_list_ctx = watch_list_scan.collect()

    # Write the complete audit context plus a budgeted, generation-bound model
    # boundary. The full JSON remains available for postflight/audit; the skill
    # reads manifest+core and lazy-loads feature bundles.
    # 简报上下文里的 portfolio 拷贝去掉 gold_dca.nav_history(~140条/3.3KB 黄金每日净值流水):
    # 简报 LLM 不逐日分析黄金(黄金有独立 cron)，dashboard 🥇卡也是直接读 portfolio.json，
    # 都用不到这段 → 纯占 token。浅拷贝只替换 gold_dca 键，不改原始 portfolio(下游仍用全量)。
    portfolio_ctx = portfolio
    _g = portfolio.get('gold_dca')
    if isinstance(_g, dict) and _g.get('nav_history'):
        _g_trim = {k: v for k, v in _g.items() if k != 'nav_history'}
        _g_trim['nav_history_omitted'] = len(_g['nav_history'])  # 留计数标记=故意省略非丢失
        portfolio_ctx = {**portfolio, 'gold_dca': _g_trim}

    active_tickers = [
        str(holding.get('ticker'))
        for region in ('hk_stocks', 'us_stocks')
        for holding in portfolio['portfolios'].get(region, {}).get('holdings', [])
        if holding.get('shares', 0) > 0
    ]
    thesis_registry_ctx = thesis_registry.registry_summary(
        WS / 'memory' / 'theses', active_tickers
    )
    thesis_docs, _ = thesis_registry.load_registry(WS / 'memory' / 'theses')
    if isinstance(retro.get('decisions'), list):
        retro['decisions'] = thesis_registry.resolve_decision_links(
            retro['decisions'], thesis_docs
        )

    # Research lifecycle work queue: a reported quarter with no primary-source
    # artifact, a management promise past its due date, a position no gate cleared.
    # Read-only — the brief reports these, it does not resolve them.
    # hk_watch costs two Tencent calls a day (HK operating companies only) and is
    # the only advance warning we have that HK results are near — see issue #99.
    research_surface_ctx = research_surface.summarize(
        portfolio=portfolio,
        catalysts=catalysts,
        hk_watch=True,
        hk_results_fetch=_fetch_hk_results_notices,
    )

    open_decisions = decision_plans.open_decisions_context(today=today)
    opportunity = _opportunity_reads(open_decisions)
    track_record = _action_track_record()
    _c = opportunity['counts']
    print(f"   🎯 加仓面: candidate {_c['candidate']} / wait {_c['wait']} / reject {_c['reject']}"
          + (f" — {opportunity['why_no_candidate']}" if opportunity['why_no_candidate'] else ''))

    context = {
        'generated_at':  datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'date':          today,
        'fx':            fx,
        'portfolio_path': str(portfolio_path),
        'snapshot_path': str(snapshot_path),
        'portfolio':     portfolio_ctx,
        'book_totals':   book,
        'concentration': {'hk': hk_conc, 'us': us_conc},
        'lookthrough_exposure': lookthrough,
        'risk_guardrail': guardrail,
        'risk_discipline': discipline,
        'breakeven_math': breakeven,
        'quant_signals': quant_signals,
        'quant_signal_review': quant_review,
        'cross_sectional_factor': cross_sectional_factor_ctx,
        'peer_residual': peer_residual_ctx,
        't0_setups': t0_setups,
        't0_setup_review': t0_review,
        'integrity': integrity,
        'us_fundamentals': us_fund,
        'retrospective': retro,
        'peer_scan':     peer_scan,
        'decision_metrics': decision_metrics,
        'reflections':   reflections,
        'risk_metrics':  risk,
        'catalysts':     catalysts,
        'news_evidence_graph': news_evidence_ctx,
        'thesis_registry': thesis_registry_ctx,
        'open_decisions': open_decisions,
        # The add side. Sits next to open_decisions deliberately: the discipline
        # half of the same question has been in this context since the start.
        'opportunity': opportunity,
        # What each kind of advice has actually been worth. Sits in the context
        # rather than only on the dashboard because the sentence it qualifies
        # ("cut 700 股, confidence 0.92") is printed in the brief.
        'action_track_record': track_record,
        'technical_setup_usage': _technical_setup_usage(),
        'research_surface': research_surface_ctx,
        'macro':         macro_trim,
        'sentiment':     sentiment_trim,
        'influencer':    influencer_trim,
        'em_news':       em_news_trim,
        'watch_list':    watch_list_ctx,
        'issues':        issues,
    }
    ctx_path = TMP_DIR / f'brief-context-{today}.json'
    try:
        generation_id = brief_context.compute_generation_id(context)
        decision_packet = brief_decision_packet.compile_packet(
            context, generation_id=generation_id
        )
        context, bundle_manifest = brief_context.write_run_bundle(
            context,
            ctx_path,
            tool_artifacts={"decision_packet": decision_packet},
        )
    except Exception as exc:
        print(f'FATAL: brief context boundary failed: {exc}', file=sys.stderr)
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'failed', slot=slot,
            reason='context_budget', detail=str(exc),
        )
        return 2

    print(f'\n═════ preflight done | {len(issues)} issues ═════')
    print(f'context: {ctx_path}')
    print(
        'model context: '
        f'{bundle_manifest["budget"]["always_loaded_bytes"]:,} / '
        f'{bundle_manifest["budget"]["max_always_loaded_bytes"]:,} bytes '
        f'({bundle_manifest["budget"]["actual_reduction_pct"]}% reduction; '
        f'≈{bundle_manifest["budget"]["estimated_tokens"]:,} est. tokens)'
    )
    for section, size in sorted(
            bundle_manifest['source_section_bytes'].items(),
            key=lambda item: item[1], reverse=True):
        print(f'  context bytes {section}: {size:,}')
    if issues:
        for i in issues:
            print(f'  ⚠️  {i}')
    workflow_outcomes.record_stage(
        job_name,
        'preflight',
        'success' if not issues else 'warning',
        slot=slot,
        issue_count=len(issues),
        context_path=str(ctx_path),
        context_generation_id=context['generation_id'],
        model_context_bytes=bundle_manifest['budget']['always_loaded_bytes'],
        step_timings=step_timings,  # additive detail: per-node ok/wall_s (#916 §1.5)
    )
    return 0 if not issues else 1


if __name__ == '__main__':
    sys.exit(main())
