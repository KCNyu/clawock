#!/usr/bin/env python3
"""
report_preflight.py — Mode 6 (briefing) harness preflight.

Runs deterministic work for the 6 briefing crons:
  HK: 开盘 09:30 / 午盘 12:00 / 午后 13:30 / 收盘 16:00
  US: 开盘 09:30 ET / 收盘 16:00 ET (runtime schedules are expressed in HKT)

Each invocation:
  1. Runs analyze_{hk,us}_stocks.py --wechat (refreshes prices, writes portfolio.json)
  2. Captures full script output (the data block report_postflight will PREPEND;
     the model never copies it — see report_postflight.assemble_message)
  3. Parses signals (WATCH/STOP/TRIM counts) and direction hints
  4. Detects anomalies (≥3% intraday moves, big floating losses)
  4b. Collects peer/rotation data so the 板块全景 section has real numbers
  5. Writes memory/.tmp/report-context-{market}-{phase}-{date}.json, where {date}
     is the RUN date (not the market-session date), and drops this market+phase's
     contexts from every other date
  6. Prints that context to stdout, then the absolute path as the final line

stdout and the file are the SAME JSON — no abridged second view to drift. It is
small because peer_scan is trimmed at the source (see trim_peer_scan), not
because the print is truncated. The model writes prose only and echoes
`context_id` back to postflight, which refuses to assemble prose against a
context that has since been replaced.

Output keys:
  raw_wechat_block:   str (script stdout; postflight prepends it verbatim)
  context_id:         str (sha256[:12] of the whole context; per-generation)
  market:             "hk" | "us"
  phase:              "open" | "mid" | "pm" | "close"
  title:              suggested WeChat title
  commit_msg:         git commit message suffix
  signal_count:       {watch, stop, trim}
  anomalies:          list of {ticker, move_pct, reason}
  index_direction:    {hk_index_pct, hstech_pct} for HK; null for US
  peer_scan:          {ticker: {theme, self_pct_1d, divergence_signal,
                      listed_peers[<=5]}} for this market's active holdings
  plan_context:       {plan_date, exec_mode, open[<=12], carried_over} — what the
                      08:00 brief already decided for this leg and has not filled
                      yet; {} when there is no open decision (see plan_surface)
  needs_risk_section: bool (true if any ALERT, or STOP+TRIM >= 2)
"""

from clawock.harness import _harness_common
from clawock.harness._harness_common import run_analyze
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from clawock.workspace import workspace_root
from clawock import sessions as trading_calendar
from clawock.decision import plans as plan_surface
from clawock.evidence import research_surface
from clawock.market_data import mover_evidence as mover_news
from clawock.utilities import PACKAGED_UTILITIES
from clawock.market_data import peer_scan

WS = workspace_root(Path.cwd())
TMP = WS / 'memory' / '.tmp'

from ._harness_common import (  # noqa: F401 — re-exported for callers/tests
    compute_context_id,
)

from clawock.automation import workflow_outcomes  # noqa: E402


def _market_closed_reason(market, phase):
    """None if the market trades now; else short reason (holiday/weekend)."""
    session = trading_calendar.phase_session(market, phase)
    return trading_calendar.closed_reason(market, session=session)


def context_path(market, phase, date):
    return TMP / f'report-context-{market}-{phase}-{date}.json'


def drop_stale_contexts(market, phase, today):
    """Delete this market+phase's context files AND per-date delivery ephemera
    (send markers, upgrade claims) from any OTHER date.

    WHY (2026-07-24 美股收盘报告): the cron payload names the file as
    `report-context-us-close-{date}.json` and the agent resolved `{date}` to the
    *market close* date (07/23) instead of the *run* date (07/24). Yesterday's
    leftover context sat at exactly that name, so the read succeeded and a
    day-old portfolio was written into the report and pushed to WeChat. Nothing
    reads a past-date context (postflight/watchdog both key on today), so the
    leftovers are pure footgun ammunition: with them gone, the same mistake is a
    loud `FileNotFoundError` instead of silently stale numbers.

    Retention would not help — the file that got misread was one day old.
    """
    # Per-date ephemera for this market+phase, cleared for every date but today's.
    # Context files are the footgun above; the send marker and the upgrade claim
    # are per-date delivery state that nothing reads across days, so left alone
    # they just accumulate in memory/.tmp forever (the report-sent-* markers from
    # 07-21 onward were all still there). Same one-run-per-day keying, same rule:
    # today's are written LATER by postflight, so dropping other-date ones is safe.
    patterns = [
        (f'report-context-{market}-{phase}-*.json', context_path(market, phase, today).name),
        (f'report-sent-{market}-{phase}-*.json',    f'report-sent-{market}-{phase}-{today}.json'),
        (f'report-upgrade-{market}-{phase}-*.claim', f'report-upgrade-{market}-{phase}-{today}.claim'),
    ]
    dropped = []
    for glob, keep in patterns:
        for path in TMP.glob(glob):
            if path.name != keep:
                try:
                    path.unlink()
                    dropped.append(path.name)
                except OSError as e:
                    print(f'   ⚠️  stale tmp cleanup failed for {path.name}: {e}',
                          file=sys.stderr)
    if dropped:
        print(f'   🧹 dropped {len(dropped)} stale report tmp file(s): {", ".join(sorted(dropped))}',
              file=sys.stderr)
    return dropped


PEER_TOP_N = 5
AUTO_PEER_TOP_N = 3


def trim_peer_scan(peers):
    """Keep the peer fields a report actually cites; drop the rest at the source.

    peer_scan was 298 of the context's ~330 lines, and that bulk is what made the
    agent pipe preflight through `| tail -80` on 2026-07-24 — which cut off the
    `date` field and started the incident. The fix is to make the context small,
    NOT to print an abridged view of a fat file: nothing but the model reads
    peer_scan from a report context (report_postflight never touches it), so a
    second representation would only be one more thing to keep in sync, and the
    printed JSON would no longer be what is on disk.

    `listed_peers` and `auto_peers` are already sorted by today's move, so their
    heads are the compact 板块 views the report asks for. private_peers /
    key_news_keywords are dropped: they are the長 tail nobody cites in a 4-6
    line briefing.
    """
    out = {}
    for ticker, scan in (peers or {}).items():
        out[ticker] = {
            'theme': scan.get('theme'),
            'self_pct_1d': scan.get('self_pct_1d'),
            'divergence_signal': scan.get('divergence_signal'),
            'listed_peers': [_peer_line(p)
                             for p in (scan.get('listed_peers') or [])[:PEER_TOP_N]],
            'auto_peers': [
                f'{p.get("label") or "同行业·自动"}｜{_peer_line(p)}'
                for p in (scan.get('auto_peers') or [])[:AUTO_PEER_TOP_N]
            ],
        }
    return out


def _peer_line(peer):
    """'RKLB 火箭实验室 +0.34% (5d +3.92%)' — one string per peer.

    A nested dict costs six JSON lines per peer and the report only ever quotes
    the name and the two moves. Flattening takes the context from 332 lines to
    ~90, which is the difference between an agent reading it and an agent piping
    it through `tail`.
    """
    def pct(v):
        return f'{v:+.2f}%' if isinstance(v, (int, float)) else 'n/a'
    name = ' '.join(x for x in (peer.get('ticker'), peer.get('name')) if x)
    return f'{name} {pct(peer.get("pct_1d"))} (5d {pct(peer.get("pct_5d"))})'


def announce_context_path(out_path):
    """Print the canonical context path as the FINAL stdout line.

    The model works from the printed JSON and echoes `context_id`, so it never
    needs to open the file; postflight resolves the same path itself. Kept for
    humans debugging a run, and printed last so it survives any `tail`.
    """
    print(f'context_path: {out_path}')


TITLE_TEMPLATES = {
    ('hk', 'open'):  '📊 港股开盘快报｜{date} 09:30',
    ('hk', 'mid'):   '☕ 港股午盘快报｜{date} 12:00',
    ('hk', 'pm'):    '🌤 港股午后快报｜{date} 13:30',
    ('hk', 'close'): '🔔 港股收盘日报｜{date}',
    ('us', 'open'):  '🌅 美股开盘快报｜{date} 09:30 ET',
    ('us', 'close'): '🌙 美股收盘日报｜{date}',
}

COMMIT_PHASE_CN = {
    'open': '开盘', 'mid': '午盘', 'pm': '午后', 'close': '收盘',
}


# `scripts/data` was deleted in #429 and the analysis moved into the package in
# #421, which added `clawock analyze-hk` / `analyze-us` but left these two callers
# pointing at the old path. Both preflights then failed on every run while still
# exiting 0, so the agent saw no error and went hunting through site-packages
# instead of writing a report (#447).
#
# PACKAGED_UTILITIES is the CLI's own map and is already guarded by
# test_harness_cli_contract, so resolving through it means these callers cannot
# drift from the commands again. sys.executable rather than a bare name: this
# runs under cron, whose PATH is /usr/bin:/bin (#438, #443).


def parse_signals(stdout):
    """本档的信号计数。实现在 _harness_common（#918）。

    换成语义读行之后这份计数有两处真实变化，都不是重构副作用：
    ALERT 第一次进得来（HK 渲染器 -8% 那档，此前这里一个字都不数），
    而 `WATCHDOG` 这类含有 WATCH 子串的行不再被数成 WATCH。
    US 的 `STOP-LOSS` 仍然算 STOP —— 词表认的是两个渲染器都会写的词。
    """
    counts, _detail = _harness_common.parse_signal_lines(stdout)
    return counts


def parse_anomalies(stdout):
    """≥3% 异动行。实现在 _harness_common —— 两个 preflight 曾各存一份（#918）。"""
    return _harness_common.parse_holdings_anomalies(stdout)


def parse_hk_indices(stdout):
    """Extract 恒指 / 恒科 day move from HK script header."""
    m = re.search(r'恒指\s+[\d,]+\s+[▲▼]([\d\.]+)%\s+恒科\s+[\d,]+\s+[▲▼]([\d\.]+)%', stdout)
    if not m:
        return None
    hsi_pct, hstech_pct = float(m.group(1)), float(m.group(2))
    if '恒指 ' in stdout:
        hsi_dir = -1 if '恒指' in stdout and '▼' in stdout.split('恒指')[1].split('恒科')[0] else 1
        hstech_dir = -1 if '▼' in stdout.split('恒科')[1][:30] else 1
        return {'hsi_pct': hsi_dir * hsi_pct, 'hstech_pct': hstech_dir * hstech_pct}
    return None


def collect_peers(market):
    """Peer/rotation data for this market's holdings, for the 板块全景 section.

    The Mode 6 SKILL asks for a sector Top 5 but preflight never supplied the
    numbers, so the agent had to improvise a peer fetch at report time. Peer
    trouble must never fail the report: any problem degrades to an empty scan.
    """
    leg = 'hk_stocks' if market == 'hk' else 'us_stocks'
    try:
        portfolio = json.loads((WS / 'portfolio.json').read_text())
        # Scope to this market's leg *before* fetching: filtering the result
        # afterwards would still pay the full cross-market network fan-out.
        # stdout is the context JSON the agent parses; diagnostics go to stderr.
        return peer_scan.collect(portfolio, log=lambda m: print(m, file=sys.stderr),
                                 legs=(leg,))
    except Exception as e:
        print(f'   ⚠️  peer scan skipped: {e}', file=sys.stderr)
        return {}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    args = parser.parse_args(argv)

    if (args.market, args.phase) not in TITLE_TEMPLATES:
        print(f'❌ invalid market+phase combo: {args.market}/{args.phase}', file=sys.stderr)
        return 2

    today = datetime.now().strftime('%Y-%m-%d')
    job_name = workflow_outcomes.job_for(args.market, args.phase)
    slot = workflow_outcomes.slot_for_job(job_name)
    workflow_outcomes.record_stage(job_name, 'preflight', 'pending', slot=slot)

    # --- Holiday/weekend gate (before any fetch): on a closed market, skip the
    # price refresh entirely (stale closes must NOT be written as a new session)
    # and write a market_closed sentinel with NO raw_wechat_block — the report
    # watchdog treats a blockless context as "never ran" and won't re-send. ---
    reason = _market_closed_reason(args.market, args.phase)
    if reason:
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'skipped', slot=slot, reason=reason
        )
        result = {'status': 'market_closed', 'market': args.market,
                  'phase': args.phase, 'date': today, 'reason': reason, 'skip': True}
        TMP.mkdir(parents=True, exist_ok=True)
        drop_stale_contexts(args.market, args.phase, today)
        out_path = context_path(args.market, args.phase, today)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        market_cn = '港股' if args.market == 'hk' else '美股'
        print(f'=== MARKET CLOSED — {market_cn}今日{reason} ({today}) ===')
        print('SKIP：不要生成报告、不要调用任何 send/postflight、本回合到此结束。')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        announce_context_path(out_path)
        return 0

    rc, stdout, stderr = run_analyze(args.market)

    if rc != 0:
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'failed', slot=slot,
            return_code=rc,
        )
        result = {
            'status': 'preflight_failed',
            'market': args.market,
            'phase':  args.phase,
            'error':  stderr[-500:] if stderr else f'rc={rc}',
        }
        TMP.mkdir(parents=True, exist_ok=True)
        drop_stale_contexts(args.market, args.phase, today)
        out_path = context_path(args.market, args.phase, today)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        announce_context_path(out_path)
        return 1

    signals = parse_signals(stdout)
    anomalies = parse_anomalies(stdout)
    indices = parse_hk_indices(stdout) if args.market == 'hk' else None
    peers = collect_peers(args.market)

    title = TITLE_TEMPLATES[(args.market, args.phase)].format(date=today)
    raw_wechat_block = stdout.strip()
    market_cn = '港股' if args.market == 'hk' else '美股'
    commit_msg = f'portfolio: {market_cn}{COMMIT_PHASE_CN[args.phase]}价格更新'

    mover_thesis = research_surface.movers_thesis_context(
        [a['ticker'] for a in anomalies]
    )

    # What was actually published behind those moves. Mover-scoped, bounded
    # by a wall-clock budget, and fails soft — a news endpoint must never
    # slow or red a reporting cron.
    mover_news_ctx = mover_news.probe(
        [a['ticker'] for a in anomalies], market=args.market,
    )

    # What the 08:00 brief already decided for this leg and has not filled yet.
    # Without it the prose re-derives the day from prices and can contradict the
    # plan it is supposed to be executing (issue #119). Never raises.
    plan_ctx = plan_surface.open_decisions_context(
        leg='HK' if args.market == 'hk' else 'US', today=today,
    )

    result = {
        'status':             'ok',
        'market':             args.market,
        'phase':              args.phase,
        'date':               today,
        # microseconds so two runs in the same wall-clock second still get distinct
        # context_ids — the id is strictly per-invocation (2026-07-24 review).
        'generated_at':       datetime.now().isoformat(timespec='microseconds'),
        'raw_wechat_block':   raw_wechat_block,
        'title':              title,
        'commit_msg':         commit_msg,
        'signal_count':       signals,
        'anomalies':          anomalies,
        'index_direction':    indices,
        'peer_scan':          trim_peer_scan(peers),
        'plan_context':       plan_ctx,
        'mover_thesis':       mover_thesis,
        'mover_news':         mover_news_ctx,
        # 语义分档，不是数数（kcn 2026-08-26：「根据合适的语意来告警，不要做
        # 硬匹配」）：ALERT 是渲染端最严重的一行（当日 -8%），它单独一条就压
        # 过两条 STOP/TRIM，所以它自己就要一段风险提示。
        'needs_risk_section': (signals['alert'] >= 1
                               or (signals['stop'] + signals['trim']) >= 2),
    }
    result['context_id'] = compute_context_id(result)

    TMP.mkdir(parents=True, exist_ok=True)
    drop_stale_contexts(args.market, args.phase, today)
    out_path = context_path(args.market, args.phase, today)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    workflow_outcomes.record_stage(
        job_name, 'preflight', 'success', slot=slot,
        context_id=result['context_id'],
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    announce_context_path(out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
