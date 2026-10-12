#!/usr/bin/env python3
"""市面标准量化因子层 — 纯算术，零 LLM 观点（kcn 2026-06-11：「纯靠 LLM 推理不行，补量化」）。

对每只活跃持仓（杠杆 ETF 按标的算，07226→HSTECH 指数）每日计算经典因子：

  趋势   ma50 / ma200 / dist_ma200_pct      经典双均线；trend_on = close>MA200 且 MA50>MA200
         golden_cross                        MA50 vs MA200（金叉/死叉）
  动量   mom_1m / mom_3m / mom_6m            21/63/126 交易日收益
         mom_12_1                            Jegadeesh-Titman 12-1 动量（252d 收益剔除最近 21d）
  均值回归 rsi14                              Wilder RSI(14)：>70 超买 / <30 超卖
         zscore20                            (close−MA20)/σ20 布林 z 分数：|z|>2 = 极端
  波动   vol20_annualized                    20d 已实现波动年化（σ_daily×√252）
         atr14_pct                           Wilder ATR(14)/close — 真实波幅
  离场   chandelier_stop                     吊灯止损 = 22d 最高价 − 3×ATR(14)（趋势跟踪标准离场）
         stop_distance_pct                   现价距吊灯线（负=已跌破，趋势单应离场）
  仓位   vol_target_weight                   波动目标仓位 = min(1, σ_target/σ_realized)，σ_target=25%
  位置   pct_52w_range                       现价在 52 周高低区间的位置（0=最低 100=最高）

写 assets/data/quant_signals.json（铁律：merge-not-overwrite——单只抓空保留旧值）。
消费方：brief context['quant_signals'] + dashboard「📊 量化因子」卡。
LLM 引用纪律：技术面判断只准引用本表数字，不得自创（SKILL 已写）。

诚实口径：这些是风控/纪律因子不是 alpha——动量/趋势有大量文献支撑但都会被洗(whipsaw)；
它们的作用是把「该不该持有/该多大仓位/何处离场」从感觉变成数字，效果靠 calibration 回头验。
"""

from clawock.safe_io import to_number as _share_number
import json
import sys
from datetime import date, datetime, timezone

from clawock import sessions as trading_calendar
from clawock import history_store
from clawock.market_data.daily_prices import clean_bars
from clawock.market_data.tencent_daily import parse_daily_bars
from clawock.instruments import require as require_instrument
from clawock.safe_io import load_json_cached, safe_write_json
from clawock.plugin_host import live as live_plugins
from clawock.workspace import workspace_root

WS = workspace_root()
PORTFOLIO = WS / 'portfolio.json'
OUT = WS / 'assets' / 'data' / 'quant_signals.json'
HIST = WS / 'assets' / 'data' / 'quant_signals_history.jsonl'

MAX_STALE_DAYS = 7
RETIRED_RETENTION_DAYS = 7

# Compatibility entry point; Tencent parsing is owned by the market-data layer.
_parse_bars = parse_daily_bars


def fetch_bars(code, cnt=400):
    """日 K，来自挂载的 `daily_bars` 插件（现网行为前复权；请求失败返回 []）。"""
    return live_plugins.service('daily_bars').fetch(code, cnt)


def compute_signals(bars):
    """The mature factor row, from the mounted `factors` plugin."""
    return live_plugins.service('factors').signals(bars)


def compute_short_history_signals(bars):
    """The 20-29-bar view, from the mounted `factors` plugin."""
    return live_plugins.service('factors').short_history(bars)


# A name with ≥30 sessions since listing can reach the mature 30-bar gate; the
# short-history fallback is for names that genuinely cannot. 45 calendar days
# ≈ 30 trading sessions, with slack for holidays. The value is policy, not a
# code constant: the single source of truth is add-alpha-policy.json's
# `short_history_max_age_days` (#643), read at call time; this module constant
# is only the fallback when the config is missing.
SHORT_HISTORY_MAX_AGE_DAYS = 45


def _policy_short_history_max_age_days() -> int:
    """`short_history_max_age_days` from add-alpha-policy.json, default 45.

    Resolved at call time so a config edit applies without a code change; a
    missing/broken config falls back to the 45-calendar-day default (#643).
    """
    try:
        policy = json.loads(
            (workspace_root() / "config" / "add-alpha-policy.json")
            .read_text(encoding="utf-8"))
        raw = policy.get("short_history_max_age_days")
        if raw is not None:
            return int(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError,
            TypeError):
        pass
    return SHORT_HISTORY_MAX_AGE_DAYS


def is_short_history_candidate(detail, run_date):
    """Genuinely-new-listing gate for the 20–29-bar fallback (#608).

    The short-history view must not rescue a mature name whose feed returned
    only 20–29 bars (a partial feed): that would bypass the deliberate 30-bar
    data-quality gate with half a signal set. Only names whose registry
    `listing_date` is present and recent (≤ the configured window, default
    SHORT_HISTORY_MAX_AGE_DAYS) are candidates; an absent or unparseable
    listing_date means "not known to be new", and the strict gate stands.
    """
    ld = (detail or {}).get('listing_date')
    if not ld:
        return False
    try:
        listing = datetime.fromisoformat(ld).date()
    except (ValueError, TypeError):
        return False
    return (run_date - listing).days <= _policy_short_history_max_age_days()


def universe_details(errors=None, portfolio=None):
    """活跃持仓 → 去重后的 signal rows，保留每行覆盖的真实持仓。

    杠杆产品使用 registry 的 signal_symbol 折到标的/1x proxy；venue 后缀
    同样从 registry 读取，绝不再默认猜成 Nasdaq。

    Per-holding tolerance (#612): one registry gap (unknown ticker, missing
    canonical Tencent symbol) must not blank the whole universe — the bad
    holding is skipped and reported via `errors` (when provided), mirroring
    the per-row fail-soft doctrine of #136. Rows carry the registry
    `listing_date` so short-history gating (#608) works for every consumer.
    """
    port = portfolio if isinstance(portfolio, dict) else load_json_cached(PORTFOLIO)
    by_code = {}
    for book in (port.get('portfolios') or {}).values():
        if not isinstance(book, dict):
            continue
        for h in book.get('holdings', []):
            if (_share_number(h.get('shares', 0)) or 0) <= 0:
                continue
            t = h.get('ticker')
            try:
                meta = require_instrument(t)
                signal_symbol = meta.get('signal_symbol') or t
                signal_meta = require_instrument(signal_symbol)
                label = signal_symbol
                code = signal_meta.get('tencent_symbol')
                note = f'{t} 的标的/1x proxy' if signal_symbol != t else ''
                if not code:
                    raise ValueError(
                        f'{signal_symbol} has no canonical Tencent symbol')
            except Exception as exc:  # noqa: BLE001 — one bad holding must not blank the rest
                if errors is not None:
                    errors.append({
                        'label': t,
                        'error': f'{type(exc).__name__}: {exc}'[:200],
                    })
                continue
            row = by_code.setdefault(code, {
                'label': label,
                'code': code,
                'note': note,
                'region': signal_meta['region'],
                'source_holdings': [],
                'listing_date': signal_meta.get('listing_date'),
            })
            row['source_holdings'].append(t)
            if note and not row['note']:
                row['note'] = note
    return list(by_code.values())


def _latest_completed_session(region, at=None):
    return trading_calendar.latest_completed_session(region, at)


def _as_date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _missing_row(detail, reason, last_good_as_of=None):
    row = {
        'code': detail['code'],
        'source_holdings': sorted(detail['source_holdings']),
        'status': 'missing',
        'row_as_of': None,
        'last_good_as_of': last_good_as_of,
        'stale_reason': reason,
        'max_age_days': MAX_STALE_DAYS,
    }
    if detail.get('note'):
        row['note'] = detail['note']
    return row


def _carry_setup_campaigns(sig, previous, row_as_of):
    """Keep a campaign id while a setup remains continuously present."""
    prior = {
        row.get('setup_id'): row.get('campaign_id')
        for row in (previous or {}).get('technical_setups') or []
        if row.get('setup_id') and row.get('campaign_id')
    }
    for setup in sig.get('technical_setups') or []:
        setup_id = setup.get('setup_id')
        setup['campaign_id'] = (
            prior.get(setup_id) or f'{setup_id}:{row_as_of.isoformat()}'
        )


def refresh_rows(previous, universe, *, run_date=None, previous_as_of=None,
                 expected_sessions=None, fetcher=fetch_bars):
    """Refresh current rows, make failures visible, and age out retired rows."""
    run_date = run_date or trading_calendar.hkt_today()
    expected_sessions = expected_sessions or {
        region: _latest_completed_session(region)
        for region in ('US', 'HK')
    }
    rows = {}
    current_labels = {detail['label'] for detail in universe}

    for detail in universe:
        label = detail['label']
        old = dict(previous.get(label) or {})
        old_as_of = old.get('row_as_of')
        # Legacy rows predate per-row freshness and may inherit the old top-level
        # date once. A visible missing marker is not a last-known-good row.
        if not old_as_of and old and not old.get('status'):
            old_as_of = previous_as_of
        last_good_as_of = old_as_of or old.get('last_good_as_of')
        bars = clean_bars(fetcher(detail['code']) or [])
        expected = expected_sessions.get(detail['region'])
        # Some providers publish a moving daily candle before the exchange has
        # closed. It is not a completed session and must not create a setup.
        if expected:
            bars = [
                bar for bar in bars
                if (_as_date(bar.get('date')) is not None
                    and _as_date(bar.get('date')) <= expected)
            ]
        sig = compute_signals(bars) if bars else None
        if sig is None and is_short_history_candidate(detail, run_date):
            # A genuinely-new name cannot reach the 30-bar mature gate, but the
            # early-trend lane needs its 20-bar-computable technical view. The
            # listing-date gate keeps a partial-feed mature name on the strict
            # gate (#608).
            sig = compute_short_history_signals(bars)
        if sig is not None:
            row_as_of = _as_date(bars[-1].get('date'))
            age_days = (run_date - row_as_of).days if row_as_of else None
            if row_as_of is None:
                rows[label] = _missing_row(
                    detail, 'latest bar has no valid date', last_good_as_of)
                continue
            if age_days > MAX_STALE_DAYS:
                rows[label] = _missing_row(
                    detail,
                    f'latest bar {row_as_of} exceeds {MAX_STALE_DAYS}-day max age',
                    row_as_of.isoformat(),
                )
                continue
            _carry_setup_campaigns(sig, old, row_as_of)
            sig.update({
                'code': detail['code'],
                'source_holdings': sorted(detail['source_holdings']),
                'status': 'fresh' if not expected or row_as_of >= expected else 'stale',
                'row_as_of': row_as_of.isoformat(),
                'max_age_days': MAX_STALE_DAYS,
            })
            if expected and row_as_of < expected:
                sig['stale_reason'] = (
                    f'latest bar {row_as_of} before expected session {expected}'
                )
            if detail.get('note'):
                sig['note'] = detail['note']
            rows[label] = sig
            continue

        old_date = _as_date(old_as_of)
        age_days = (run_date - old_date).days if old_date else None
        if old and age_days is not None and age_days <= MAX_STALE_DAYS:
            old.update({
                'code': detail['code'],
                'source_holdings': sorted(detail['source_holdings']),
                'status': 'stale',
                'row_as_of': old_date.isoformat(),
                'stale_reason': 'fetch failed or returned insufficient bars',
                'max_age_days': MAX_STALE_DAYS,
            })
            if detail.get('note'):
                old['note'] = detail['note']
            rows[label] = old
        else:
                rows[label] = _missing_row(
                detail, 'fetch failed and no usable last-known-good row',
                last_good_as_of)

    for label, old_value in previous.items():
        if label in current_labels:
            continue
        old = dict(old_value or {})
        retired_since = _as_date(old.get('retired_since')) or run_date
        if (run_date - retired_since).days >= RETIRED_RETENTION_DAYS:
            continue
        old.update({
            'status': 'retired',
            'retired_since': retired_since.isoformat(),
            'retention_days': RETIRED_RETENTION_DAYS,
            'stale_reason': 'not in current signal universe',
        })
        old.setdefault('row_as_of', previous_as_of)
        rows[label] = old
    return rows


def provisional_setups(universe=None, *, region=None, fetch=None):
    """The same setup rules, evaluated against the still-open session's bar.

    The daily pipeline runs these rules once, at 08:00, on completed bars — so a
    reclaim of MA20 at 11:00 or a 20-day breakout at 14:30 is a fact the
    decision surface does not learn until the next morning. Every one of these
    signals is currently a day late (#515). This re-runs the *identical* rules
    (`compute_signals`, no thresholds touched, no rules added) against a bar
    that includes the live session.

    That bar has not closed, and two of the three rules are statements about a
    close. So every row is returned as provisional — `confirmed_at_close` is
    False and the wording callers must use is "if it closes here", never "it
    triggered". A provisional row is a reason to look, not an entry.

    Fail-soft as a *value*: a ticker whose bars cannot be fetched is reported in
    `errors`, never silently dropped, because a quote feed that stopped
    answering looks exactly like a day with no setups (#136).
    """
    rows, errors = [], []
    fetcher = fetch or fetch_bars
    run_date = trading_calendar.hkt_today()
    for detail in (universe if universe is not None else universe_details()):
        if region and detail.get('region') != region:
            continue
        label = detail.get('label')
        try:
            bars = fetcher(detail['code'], 400)
            sig = compute_signals(bars)
            if sig is None and is_short_history_candidate(detail, run_date):
                sig = compute_short_history_signals(bars)
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not blank the rest
            errors.append({'label': label, 'error': f'{type(exc).__name__}: {exc}'[:200]})
            continue
        if sig is None:
            # `fetch_bars` returns [] on a failed request rather than raising.
            # `compute_signals` answers None below 30 bars and the short-history
            # fallback answers None below 20 — so the ordinary production
            # failure arrives as a value, not an exception, and an unguarded
            # `.get` here would escape the loop and take every row already
            # collected with it.
            errors.append({'label': label,
                           'error': 'no_bars' if not bars else f'insufficient_bars({len(bars)})'})
            continue
        for setup in sig.get('technical_setups') or []:
            rows.append({
                'label': label,
                'holdings': list(detail.get('source_holdings') or []),
                'setup_id': setup.get('setup_id'),
                'label_zh': setup.get('label'),
                'entry_price': setup.get('entry_price'),
                'invalidation_price': setup.get('invalidation_price'),
                'detail': setup.get('detail'),
                # The whole point of the field: this was computed on an open bar.
                'confirmed_at_close': False,
                'last_price': sig.get('close'),
            })
    out = {'rows': rows, 'confirmed_at_close': False}
    if errors:
        out['errors'] = errors
    return out


def main(argv=None):
    del argv
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
        except Exception:
            prev = {}
    universe = universe_details()
    rows = refresh_rows(
        prev.get('rows') or {},
        universe,
        previous_as_of=prev.get('as_of'),
    )
    for detail in universe:
        label = detail['label']
        sig = rows[label]
        if sig['status'] == 'fresh':
            print(f"  {label:8s} {sig['tag']}  RSI {sig['rsi14']}  z {sig['zscore20']}  "
                  f"距200线 {sig['dist_ma200_pct']}%  吊灯距 {sig['stop_distance_pct']}%")
        else:
            print(f"  warn: {label} {sig['status']} — {sig.get('stale_reason')}",
                  file=sys.stderr)

    # What the mounted row sized against, not a second copy of the number.
    sigma_target = live_plugins.service('factors').describe()['sigma_target']
    out = {
        'as_of': trading_calendar.hkt_today().isoformat(),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sigma_target': sigma_target,
        'max_stale_days': MAX_STALE_DAYS,
        'retired_retention_days': RETIRED_RETENTION_DAYS,
        'rows': rows,
        'formulas': {
            'trend': 'trend_on = close>MA200 且 MA50>MA200（双均线）；golden_cross = MA50>MA200',
            'momentum': 'mom_Nm = N 月收益；mom_12_1 = 252d 收益剔除最近 21d（Jegadeesh-Titman）',
            'mean_reversion': 'rsi14 = Wilder RSI(14)，>70 超买/<30 超卖；zscore20 = (close−MA20)/σ20，|z|>2 极端',
            'vol': 'vol20 = 20d 日收益 σ×√252；atr14_pct = Wilder ATR(14)/close',
            'exit': 'chandelier_stop = 22d 最高价 − 3×ATR(14)；stop_distance_pct<0 = 已破线（趋势单标准离场）',
            'sizing': f'vol_target_weight = min(1, {sigma_target}/vol20) — 波动越高仓位上限越小',
        },
        'reading_discipline': ('因子是纪律不是预言：趋势/动量管「该不该持有」，RSI/z 管「别在极端点动手」，'
                               '吊灯线管「趋势单何处离场」，vol-target 管「该拿多大」。'
                               'LLM 技术面判断只准引用本表，效果由 calibration 事后验证。'),
    }
    safe_write_json(OUT, out)
    print(f'  wrote {OUT.relative_to(WS)} ({len(rows)} symbols)')

    # 自迭代闭环第一半：每日信号留痕（JSONL，一天一行）。quant_signal_review.py 用
    # 它对账 forward return → 因子 edge 表。同日重跑替换当天行（盘中多次刷新取最后）。
    hist_line = json.dumps({'as_of': out['as_of'],
                            'rows': {k: {f: v.get(f) for f in
                                         ('row_as_of', 'close', 'trend_on', 'golden_cross', 'rsi14', 'zscore20',
                                          'stop_distance_pct', 'mom_1m', 'dist_ma200_pct')}
                                     for k, v in rows.items()
                                     if v.get('status') == 'fresh'}}, ensure_ascii=False)
    # 热窗写工作文件、冷段进 archive（#951）；读侧（signal_review）走
    # history_store.load_series，窗口与命中率不受影响。
    rows = [row for row in history_store.load_series(HIST)
            if row.get('as_of') != out['as_of']]
    rows.append(json.loads(hist_line))
    rows = history_store.write_series(HIST, rows)
    print(f'  history: {len(rows)} days in {HIST.name}')


if __name__ == '__main__':
    main()
