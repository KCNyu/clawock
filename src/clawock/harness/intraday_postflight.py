#!/usr/bin/env python3
"""
intraday_postflight.py — Mode 7 (intraday) harness postflight.

Validates the LLM-generated intraday check-in.

Usage: `--text-file PATH` (canonical — write the report to a file first, then call
this). Stdin is still accepted for manual runs, but the cron/SKILL path must use
--text-file: heredoc/`<<<` plumbing has repeatedly failed (2026-07-23 10:00 HK:
the model called postflight with no stdin at all, the empty read produced four
misleading content issues, and the run was flagged error even though the retry
delivered fine).

Empty or stale input is reported as `status: input_error` — a plumbing failure,
distinct from `fail` (the report itself is bad). It still exits non-zero: this is
the delivery gate, and a false green is worse than a false red.

Input (the only shape, since #1279): `--context-id` + `--text-file`. The model
writes ONLY the ▎我的看法 prose; assemble_message() prepends the harness-owned
data block at send time, so the block never makes a round trip through the model.

  The `legacy` shape — no --context-id, the model's text IS the whole message and
  the data block is checked for a byte-exact copy afterwards — was retired in
  #1279. Its stated removal condition (every cron payload passing --context-id)
  had been met since the payload rewrite, so it was a branch that could no longer
  run and therefore could not be trusted to work when reached.

Validates:
  1. ▎我的看法 段必须存在 + 段内容 ≥ 60 字（防敷衍 1 句话）
  2. 总长度闸与 Mode 6 共用 clawock.harness.validation.REPORT_CHAR_LIMITS（防复读死循环，不是写作目标）
  3. 若 preflight should_alert=true：正文须提到至少一个异动票，且（有 ALERT/WATCH/STOP/TRIM 信号时）至少一个信号票
  4. 无敷衍 phrases

Note: Mode 7 does NOT commit portfolio.json. For every usable preflight context,
including a slot whose prose is rejected, it rebuilds dashboard.json and commits
only semantic changes. Every slot also updates the local heartbeat ledger, which
the existing single publisher exposes without introducing another git writer.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from clawock.harness.validation import (
    ADVISORY_MARK,
    REPORT_CHAR_LIMITS,
    advisory_prefix,
    categorize_issues,
    check_identifier_leak,
    check_numeric_claims,
    check_pipeline_self_reference,
    mentions_ticker,
    postflight_exit_code,
    product_status,
    split_advisory,
    validate_forbidden_phrases,
)
from ._harness_common import (  # noqa: E402
    dashboard_publication_state,
    git_cmd,
    push_with_rebase_retry,
    SIGNAL_LEVELS,
    rebuild_dashboard,
    snapshot_date_for_now,
)
from ._watchdog_common import (  # noqa: E402
    resolve_wechat_target, send_wechat, cosend_telegram, already_delivered,
    delivered_channels,
    claim_send, mark_send_started, release_claim, log, send_per_policy,
)

from clawock.workspace import workspace_root
from clawock import sessions as trading_calendar
from clawock.safe_io import safe_write_json, safe_write_text

WS = workspace_root()
_CHECKOUT = WS
TMP = WS / 'memory' / '.tmp'

from clawock.automation import cron_heartbeat  # noqa: E402
from clawock.automation import delivery_receipts  # noqa: E402
from clawock.harness import intraday_delta  # noqa: E402
from clawock.harness.intraday_preflight import can_silence  # noqa: E402

# A report file older than this is assumed to be a previous slot's leftover. Kept
# below the 30min slot cadence (and aligned with the already_delivered window) so a
# forgotten write is refused instead of silently re-publishing a stale report.
REPORT_MAX_AGE_MIN = 20

REQUIRED_SECTION = '▎我的看法'
# One table with report/brief: this file used to carry its own copy, which
# never gained '数据缺失（占位）' and let that placeholder ship intraday (#1776).
from clawock.harness.report import FORBIDDEN_PHRASES  # noqa: E402
CRITICAL_KEYWORDS = ['缺段标记', '未包含原始数据块', '敷衍词',
                     '表格行未 verbatim', '策略冲突', '策略证据不足']
JUDGMENT_SOFT_LIMIT = 600
JUDGMENT_REVIEW_LIMIT = 900


def load_context(market):
    path = TMP / f'intraday-context-{market}-latest.json'
    if not path.exists():
        return None, f'preflight latest context 不存在: {path.name}'
    try:
        return json.loads(path.read_text()), None
    except Exception as e:
        return None, f'context 解析失败: {e}'


def read_report_text(market, text_file):
    """Return (text, input_error). Plumbing failures never reach validate()."""
    hint = (f'Step 3 应先把 ▎我的看法 散文写入 memory/.tmp/intraday-prose-{market}.md，'
            f'再用 --text-file + --context-id 调用 postflight；'
            f'不要用 heredoc/here-string 重定向喂 stdin')
    if text_file:
        path = Path(text_file)
        if not path.exists():
            return '', f'报告文件不存在: {path} — {hint}'
        age_min = (datetime.now().timestamp() - path.stat().st_mtime) / 60
        if age_min > REPORT_MAX_AGE_MIN:
            return '', (f'报告文件 {path.name} 已 {age_min:.0f} 分钟未更新 '
                        f'(> {REPORT_MAX_AGE_MIN} 分钟上限) — 疑似上一个 slot 的旧报告，'
                        f'拒绝投递；{hint}')
        text = path.read_text()
    else:
        text = sys.stdin.read()

    if not text.strip():
        src = f'--text-file {text_file}' if text_file else 'stdin'
        return '', f'空输入 ({src}) — postflight 没收到任何报告文本；{hint}'
    return text, None


def input_error(market, err):
    """Exit path for empty/stale/missing input: loud, single-cause, still non-zero."""
    # Attribute the failure to the slot the preflight context was built for, not to
    # whatever slot the wall clock happens to be in now. A run that starts at 10:00
    # and hits empty input at 10:31 would otherwise stamp a phantom 10:30 failure,
    # and the retry that succeeds would mark 10:00 completed — leaving a slot in the
    # health ledger that never actually failed. Context is best-effort here: an
    # input error must still be recorded when the context is missing too.
    ctx, _ = load_context(market)
    hb = (ctx or {}).get('heartbeat') or {}
    cron_heartbeat.record(market, 'postflight_failed', failure_stage='input',
                          job_name=hb.get('job'), slot=hb.get('slot'))
    print(f'error: {err}', file=sys.stderr)
    result = {
        'status':        'input_error',
        'market':        market,
        'time':          datetime.now().strftime('%H:%M'),
        'issues':        [err],
        'wechat_prefix': '',
        'n_chars':       0,
        'wechat_sent':   None,
        'telegram_sent': None,
        'dashboard_published': False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2


def normalize_intraday_insights(path, generated_at=None, *, written_after=None):
    """Replace model metadata with the current harness generation timestamp.

    The model owns narrative only. Malformed/missing sidecars are dashboard
    degradation, never a reason to suppress the deterministic market report.
    """
    if not path.exists():
        return False
    try:
        if written_after:
            cutoff = datetime.fromisoformat(str(written_after).replace('Z', '+00:00'))
            # New preflights always carry HKT offset. Older stored contexts may
            # be naive; they cannot provide a trustworthy cutoff.
            if cutoff.tzinfo is not None and path.stat().st_mtime < cutoff.timestamp() - 1:
                raise ValueError('sidecar predates this preflight')
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError('top-level JSON must be an object')
        banner, movers = payload.get('status_banner'), payload.get('movers')
        if not isinstance(banner, str) or len(banner) > 50:
            raise ValueError('status_banner must be text of at most 50 characters')
        if not isinstance(movers, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                or len(value) > 40 for key, value in movers.items()):
            raise ValueError('movers must map tickers to text of at most 40 characters')
        canonical = {
            'generated_at': generated_at or datetime.now(timezone.utc).isoformat(
                timespec='seconds').replace('+00:00', 'Z'),
            'status_banner': banner,
            'movers': movers,
        }
        safe_write_json(str(path), canonical)
        return True
    except Exception as exc:
        print(f'warn: {path.name} 解析/规范化失败 — dashboard status_banner 将忽略: '
              f'{exc}', file=sys.stderr)
        return False


# Card block 11 (docs/architecture/intraday-agent.md §4): the model's next
# trigger, pulled out of the judgment into one structured, checkable line that
# sits above ▎我的看法. It used to be the last clause of a paragraph
# (「…下一触发：恒科 4,300 / 07226 3.0 / 02208 8.84（已破，待收线对账）」,
# 2026-09-25 14:33), where nothing could check it and kcn had to find it.
NEXT_TRIGGER = '下一触发：'
_NEXT_TRIGGER_LINE = re.compile(r'^[ \t]*下一触发[ \t]*[:：][ \t]*(\S.*?)[ \t]*$', re.MULTILINE)
_NEXT_TRIGGER_ITEM = re.compile(r'[；;]|\s/\s')
_TRIGGER_NUMBER = re.compile(r'(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?')
_TABLE_TICKER = re.compile(r'^\|\s*([A-Z0-9]{2,6})\s*\|', re.MULTILINE)
# Names a trigger may be about besides the tickers the context carries.
TRIGGER_INDEX_NAMES = ('恒指', '恒生指数', '恒科', '恒生科技', 'HSI', 'HSTECH', '纳指',
                       '纳斯达克', '标普', 'SPX', 'NDX', 'VIX', '组合', '账户')


def split_next_trigger(prose):
    """`(line, prose_without_it)`; `line` is None when the prose has none."""
    text = prose or ''
    match = _NEXT_TRIGGER_LINE.search(text)
    if not match:
        return None, text
    rest = (text[:match.start()] + text[match.end():]).strip('\n')
    return NEXT_TRIGGER + match.group(1), re.sub(r'\n{3,}', '\n\n', rest)


def _context_tickers(ctx):
    names = {row.get('ticker') for row in (ctx.get('full_holdings') or [])}
    names |= {row.get('ticker') for row in (ctx.get('anomalies') or [])}
    names |= {row.get('ticker') for row in
              ((ctx.get('add_side_reads') or {}).get('rows') or [])}
    names |= {row.get('label') for row in
              ((ctx.get('opportunity_radar') or {}).get('rows') or [])}
    names |= set((ctx.get('holding_policies') or {}))
    for block in (ctx.get('raw_wechat_block'), ctx.get('analyzer_block')):
        names |= set(_TABLE_TICKER.findall(block or ''))
    return {str(name) for name in names if name and name != '代码'}


def _context_numbers(ctx):
    """Every number the context states, as JSON values or inside its text."""
    seen = set()

    def walk(value):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            seen.add(round(abs(float(value)), 4))
        elif isinstance(value, str):
            for whole, frac in _TRIGGER_NUMBER.findall(value):
                seen.add(round(float((whole + frac).replace(',', '')), 4))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(ctx)
    return seen


def check_next_trigger(prose, ctx):
    """One escalating issue when the 下一触发 line is missing or unverifiable.

    Structured means each item (split on ；/ ` / `) names a subject — a ticker
    in the context or an index — and quotes a level the context contains,
    literally. A line that reads authoritative must be checkable; one issue
    for the whole line so a single bad line counts once.
    """
    line, _ = split_next_trigger(prose)
    if line is None:
        inline = '下一触发' in (prose or '')
        return [('「下一触发」没有单独成行' if inline else '缺「下一触发」行')
                + '（单独一行：下一触发：<标的> <条件><价位>；…）']
    tickers, known = _context_tickers(ctx), _context_numbers(ctx)
    problems = []
    for item in [part.strip() for part in _NEXT_TRIGGER_ITEM.split(line[len(NEXT_TRIGGER):])
                 if part.strip()]:
        bare = item
        for ticker in sorted(tickers, key=len, reverse=True):
            bare = bare.replace(ticker, ' ')
        if not any(mentions_ticker(item, ticker) for ticker in tickers) and not any(
                name in item for name in TRIGGER_INDEX_NAMES):
            problems.append(f'无标的「{item[:16]}」')
        numbers = [whole + frac for whole, frac in _TRIGGER_NUMBER.findall(bare)]
        if not numbers:
            problems.append(f'无价位「{item[:16]}」')
        missing = [raw for raw in numbers
                   if round(float(raw.replace(',', '')), 4) not in known]
        if missing:
            problems.append(f"价位不在 context：{'、'.join(missing[:3])}")
    if not problems:
        return []
    return ['「下一触发」无法核对（' + '；'.join(problems[:3]) + '）']


def assemble_message(ctx, prose):
    """Build the delivered check-in from harness-owned data + model-owned prose.

    Mode 7 used to make the deterministic data block round-trip through the LLM:
    preflight put it in the context, the payload ordered the model to retype it
    character for character, and validate() diffed the copy. Mode 6 dropped that
    on 2026-07-24; Mode 7 was left behind and kept paying for it — on 2026-07-28
    00:30 the model padded RKLX's 浮$ cell with one extra space, the strict
    substring check raised a CRITICAL, and the whole ▎我的看法 段 was dropped in
    favour of the bare data block. The table was correct; only its whitespace
    was not.

    Prepending here removes the round trip: the numbers in the delivered message
    come from the context file at send time, so they cannot be paraphrased or
    table-mangled — no copy instruction and no verbatim rule needed. Mode 7 has
    no separate `title`; raw_wechat_block already opens with the titled first
    line, so the block alone is the prefix.
    """
    # Layout contract (intraday_preflight): the data block comes first and the
    # judgment follows the table and the rest of the block (kcn 2026-09-25,
    # after #1863 had moved it above the table: 「表格位置怎么倒置了？」).
    # Block 11 before block 12: the structured 下一触发 line leaves the
    # judgment and sits directly above ▎我的看法.
    trigger, judgment = split_next_trigger(prose)
    parts = [(ctx.get('raw_wechat_block') or '').strip(), trigger or '',
             (judgment or '').strip()]
    return '\n\n'.join(p for p in parts if p)


WECHAT_BOLD = '**'


def _bold_cell(cell):
    body = cell.strip()
    if not body:
        return cell
    lead, trail = cell[:len(cell) - len(cell.lstrip())], cell[len(cell.rstrip()):]
    return f'{lead}{WECHAT_BOLD}{body}{WECHAT_BOLD}{trail}'


def render_for_channel(message, ctx, channel):
    """The card as one channel shows it (contract §4, channels).

    WeChat renders markdown bold inside a table, so the rows the `↑` line
    names as new move/trigger (`card_marks.new`) are bolded cell by cell there.
    Telegram shows the table as a fixed-width block where `**` would be
    literal and break the alignment, so it always gets the plain card. Bold is
    the only difference: with `**` removed the two payloads are equal, and a
    table cell's text never changes.
    """
    rows = set(((ctx or {}).get('card_marks') or {}).get('new') or [])
    if channel != 'wechat' or not rows:
        return message
    out = []
    for line in message.splitlines():
        stripped = line.strip()
        cells = line.split('|')
        if (stripped.startswith('|') and stripped.endswith('|') and len(cells) > 2
                and cells[1].strip() in rows):
            line = '|'.join([cells[0], *[_bold_cell(c) for c in cells[1:-1]], cells[-1]])
        out.append(line)
    return '\n'.join(out)


def validate(text, ctx, model_text):
    """Validate the delivered check-in.

    `text` is what gets sent; `model_text` is the part the MODEL wrote — the prose
    alone. The content rules — 我的看法 段, anomaly mention, forbidden phrases,
    numeric claims — MUST run against model_text, never the assembled body. The
    prepended block itself contains the anomaly tickers and section-looking tokens,
    so checking the body would let prose that names none of the movers pass because
    the table does. Only the length limit is a property of the assembled body.
    (Same split as report_postflight.validate — see its docstring.)

    Three tiers, and which one a rule sits in is deliberate:

    - critical (`CRITICAL_KEYWORDS`, hard length): the report fails outright;
    - escalating: counted against `warn_max` — the alert-slot rules (anomaly and
      signal tickers must be named in prose) live here, because naming what
      fired is what an alert slot is for, and so do context field names in the
      prose (an identifier is never trading language);
    - advisory (`ADVISORY_MARK`): shown, never counted — secondary reads such as
      plan triggers and add-side verdicts, numeric provenance, pipeline jargon.

    `fail` is never silence: it delivers the fail-closed data block with a
    banner (#135). Moving a rule to a looser tier is a policy change, not a
    consistency fix (#1635).
    """
    issues = []
    checked = model_text
    # The 下一触发 line is its own block; the judgment's floor is measured
    # without it.
    _, judgment = split_next_trigger(checked)

    if REQUIRED_SECTION not in checked:
        issues.append(f'缺段标记 "{REQUIRED_SECTION}"')
    else:
        # 我的看法 段必须 ≥ 60 字（否则就是敷衍 1 句结案）
        section_body = (judgment.split(REQUIRED_SECTION, 1)[1].strip()
                        if REQUIRED_SECTION in judgment else '')
        # cut to next section (▎XXX) or end
        next_marker = section_body.find('\n▎')
        if next_marker > 0:
            section_body = section_body[:next_marker]
        section_body = section_body.strip()
        # An unchanged slot (always_full on) is honest in one line: "本档无实质
        # 变化，下一触发 X". The 60-char floor would push it into padding or an
        # invented move, so a short body passes only when it says no change.
        honest_quiet = bool(ctx.get('semantic_unchanged')) and re.search(
            r'无实质变化|没有实质变化|无新变化|没有新变化|无变化', section_body)
        if len(section_body) < 60 and not honest_quiet:
            issues.append(
                f'"{REQUIRED_SECTION}" 段仅 {len(section_body)} 字，太敷衍 '
                f'(< 60 软下限)；需引用具体票 + 一行判断'
            )

    if ctx.get('semantic_unchanged') and re.search(r'新异动|新触发|本档新', checked):
        issues.append('语义未变的档位，判断却写了新异动/新触发 (advisory)')

    # Only the model slot is bounded here; the harness-owned table can be long
    # without forcing the model to copy it or making a sound quote fail.
    if len(checked) > JUDGMENT_REVIEW_LIMIT:
        issues.append(f'判断段长度 {len(checked)} 字 > {JUDGMENT_REVIEW_LIMIT} 软上限 (warn)')
    elif len(checked) > JUDGMENT_SOFT_LIMIT:
        issues.append(f'判断段长度 {len(checked)} 字 > {JUDGMENT_SOFT_LIMIT} 软上限 (warn)')

    # Length is a property of what actually gets pushed to WeChat, so it — and
    # only it — measures the assembled body. The thresholds are Mode 6's, shared
    # rather than copied: this file used to carry its own 3000/3500 literals,
    # so the two modes could drift apart with nothing to notice.
    n = len(text)
    soft, hard = REPORT_CHAR_LIMITS['soft'], REPORT_CHAR_LIMITS['hard']
    if n > hard:
        issues.append(f'报告长度 {n} 字 > {hard} 上限')
    elif n > soft:
        issues.append(f'报告长度 {n} 字 > {soft} 软上限 (warn)')

    # Two independent requirements, not a fallback chain. An alert slot can
    # carry anomalies AND signals; the signal check used to live in an `elif`
    # under "no anomalies", so naming one mover let every STOP/ALERT line go
    # unmentioned (#1630). Levels come from the one list decide_alert counts.
    if ctx.get('should_alert'):
        anomaly_tickers = [a['ticker'] for a in ctx.get('anomalies', [])]
        mentioned = [t for t in anomaly_tickers if mentions_ticker(checked, t)]
        if anomaly_tickers and not mentioned:
            issues.append(f'should_alert=true 但报告未提任何异动票 ({", ".join(anomaly_tickers)})')
        signal_tickers = [
            row.get('ticker') for row in (ctx.get('signals_detail') or [])
            if row.get('ticker') and str(row.get('level', '')).upper()
            in SIGNAL_LEVELS
        ]
        if signal_tickers and not any(
                mentions_ticker(checked, ticker) for ticker in signal_tickers):
            issues.append(
                'should_alert=true 但报告未提任何信号票 '
                f'({", ".join(signal_tickers[:3])})')

    # 加仓侧的读数 (#755)。它的三条输入(异动/机会雷达/早期趋势)以前全都算好了却从没
    # 进过正文,所以模板加了要求之后必须配一条闸——否则就是又一个「写了没人写」。
    # advisory:它只能提醒漏写,不许把一份已经可发的报告变成不发
    # (feedback-detect-but-never-silence)。
    # 计划触发线已破却一个字没写 (2026-09-07)。那天 00100 的 ≥365 减仓线被打穿
    # 7.7%,八个槽的正文一句没提;块里已经印了那一行,这条闸管的是正文有没有认。
    # 与加仓侧同档:advisory —— 只提醒漏写,不许把一份已经可发的报告变成不发
    # (feedback-detect-but-never-silence)。
    trigger_rows = ctx.get('plan_triggers') or []
    if trigger_rows and not any(mentions_ticker(checked, row.get('ticker')) for row in trigger_rows):
        named = '/'.join(
            f"{row['ticker']} {row['condition_price']:g}" for row in trigger_rows[:3])
        issues.append(
            f'计划触发线已破但报告一个都没写 ({named}) {ADVISORY_MARK}')

    add_rows = (ctx.get('add_side_reads') or {}).get('rows') or []
    if add_rows and not any(mentions_ticker(checked, row.get('ticker')) for row in add_rows):
        verdicts = '/'.join(f"{row['ticker']} {row['verdict']}" for row in add_rows[:3])
        issues.append(
            f'加仓侧读数非空但报告一个都没写 ({verdicts}) {ADVISORY_MARK}')

    issues.extend(validate_forbidden_phrases(checked, FORBIDDEN_PHRASES))

    # 数字必须来自 context —— 一条聚合 warn，见 check_numeric_claims
    issues.extend(check_numeric_claims(checked, ctx))

    # 下一触发 —— escalating，见 check_next_trigger
    issues.extend(check_next_trigger(checked, ctx))

    # 管线术语 —— advisory，见 check_pipeline_self_reference
    issues.extend(check_pipeline_self_reference(checked))
    # 字段名/枚举值 —— escalating，见 check_identifier_leak (2026-09-25 14:33
    # 「semantic_unchanged」原样印进正文、上面那条词表没拦住)
    issues.extend(check_identifier_leak(checked))

    for ticker, policy in (ctx.get('holding_policies') or {}).items():
        if not policy.get('forbid_reduce_advice'):
            continue
        for sentence in re.split(r'[。；\n]', checked):
            # `\b` never fires between a code and CJK ("建议00100立即减仓"),
            # which is ordinary Chinese prose; `mentions_ticker` handles it (#1852).
            if not mentions_ticker(sentence, ticker):
                continue
            if not re.search(r'砍仓|砍掉|清仓|减仓|止损|(?<![A-Za-z])(?:cut|trim)(?![A-Za-z])',
                             sentence, re.IGNORECASE):
                continue
            # A factual mention of the old open order is necessary to explain
            # a strategy conflict. Only prescriptive copy breaches the policy.
            # A sentence may mention the old plan and then issue a new order;
            # evaluate each clause so "旧计划" cannot exempt the next clause.
            for clause in re.split(r'[，,]', sentence):
                if not re.search(r'砍仓|砍掉|清仓|减仓|止损|(?<![A-Za-z])(?:cut|trim)(?![A-Za-z])',
                                 clause, re.IGNORECASE):
                    continue
                directive = re.search(
                    r'建议|应当|应该|必须|立即|现在|继续|执行|先砍|先减|砍\s*\d|减\s*\d',
                    clause)
                if directive and not re.search(
                        r'不(?:再|要|应|建议|重复)[^。；，,\n]{0,35}'
                        r'(?:砍仓|砍掉|清仓|减仓|止损|(?<![A-Za-z])(?:cut|trim)(?![A-Za-z]))',
                        clause, re.IGNORECASE):
                    issues.append(f'{ticker} 策略冲突：盘中判断建议了砍仓/减仓/止损')
                    break

    unavailable_checks = [row for row in (ctx.get('strategy_checks') or [])
                          if row.get('status') == 'unavailable']
    if unavailable_checks:
        for sentence in re.split(r'[。；\n]', checked):
            if not re.search(r'未触发|未达到|没到|未破', sentence):
                continue
            if ('P0' in sentence or any(
                    row.get('ticker') and mentions_ticker(sentence, row['ticker'])
                    and (('单日' in sentence or '今日' in sentence)
                         if row.get('window') == 'session'
                         else ('五日' in sentence or '五交易日' in sentence
                               or '单周' in sentence))
                    for row in unavailable_checks)):
                issues.append('策略证据不足：来源不可用时宣称升级条件未触发')
                break

    return issues


def categorize(issues):
    def is_hard_char_limit(issue):
        return '字 >' in issue and '上限' in issue and '软上限' not in issue

    return categorize_issues(
        issues, CRITICAL_KEYWORDS, warn_max=2, extra_critical=is_hard_char_limit,
    )


def delivery_marker_payload(ctx, *, ts, sent_ok, tg_ok, first_line, market, out,
                            delivery_state='delivered'):
    """Build the watchdog marker with the preflight slot as its identity.

    `delivery_state` distinguishes a full report from the fail-closed data block
    (#135): both are real deliveries — the watchdog must not re-send either —
    but only one of them carried the model's prose.

    `context_id` and `context_generated_at` name the preflight invocation this
    body was built from. Without them the only link back to the delivered report
    was its first line, which carries the generation minute — so when openclaw
    auto-retried a run that had already delivered, the retry's preflight rewrote
    the context, the first lines disagreed, and the watchdog mirrored a report kcn
    already had (#458, 2026-08-10 HK 10:30 and 11:30). Mode 6's marker has carried
    both fields since 2026-08-03; Mode 7's context always had them and threw them
    away here.
    """
    heartbeat = ctx.get('heartbeat') or {}
    return delivery_receipts.build_receipt(
        ts=ts, sent_ok=sent_ok, tg_ok=tg_ok, out=out,
        first_line=first_line,
        market=market,
        job=heartbeat.get('job'),
        slot=heartbeat.get('slot'),
        context_id=ctx.get('context_id'),
        context_generated_at=ctx.get('generated_at'),
        delivery_state=delivery_state,
    )


def publish_data_plane(market):
    """Publish deterministic dashboard outputs, independent of prose quality."""
    try:
        ok, _ = rebuild_dashboard()
        publication_state = dashboard_publication_state(WS)
        # No dashboard outputs here: #314 untracked them, and `git add` on a
        # gitignored path fails rather than skipping, which would abort the
        # snapshot commit too.
        paths = ['logs/dashboard_build_status.json']
        snap = snapshot_date_for_now()
        if snap:
            paths.append(f'memory/snapshots/{snap}.json')
        added, _ = git_cmd('add', '--', *paths)
        if not added:
            return 'git_add_failed', False
        # git diff --cached --quiet returns 0 when there is NO diff
        clean, _ = git_cmd('diff', '--cached', '--quiet', '--', *paths)
        if clean:
            return ('current', False) if ok else (publication_state, False)
        msg = (
            f"dashboard: intraday refresh "
            f"({market} {datetime.now().strftime('%H:%M HKT')})"
        )
        committed, _ = git_cmd('commit', '-m', msg, '--', *paths)
        if not committed:
            return 'commit_failed', False
        pushed, _ = push_with_rebase_retry()
        if not pushed:
            return 'committed_local', False
        # The status file must reach master even when the data-plane push failed;
        # otherwise the off-host health check keeps reading the previous green
        # record. Report the actual public outcome after that diagnostic commit.
        return ('published', True) if ok else (publication_state, False)
    except Exception as exc:
        print(f'warn: dashboard auto-publish failed: {exc}', file=sys.stderr)
        return 'publish_failed', False


def finish_no_change(ctx, args, *, allow_soft_review=False):
    if args.context_id != ctx.get('context_id') or not can_silence(
            ctx, allow_soft_review=allow_soft_review):
        return input_error(args.market, 'no_change context 不匹配或健康闸未通过')
    data_plane_status, dashboard_published = publish_data_plane(args.market)
    if data_plane_status not in {'published', 'current'}:
        return input_error(args.market, f'no_change dashboard 发布失败: {data_plane_status}')
    try:
        if not intraday_delta.persist_delivered_state(WS, ctx):
            return input_error(args.market, 'no_change 语义游标未写入')
    except OSError as exc:
        return input_error(args.market, f'no_change 语义游标写入失败: {exc}')
    heartbeat = ctx.get('heartbeat') or {}
    marker = delivery_receipts.receipt_path(TMP, 'intraday', market=args.market)
    first = (ctx.get('raw_wechat_block') or '').splitlines()
    try:
        safe_write_text(str(marker), json.dumps(delivery_marker_payload(
            ctx, ts=int(datetime.now().timestamp() * 1000), sent_ok=None,
            tg_ok=None, first_line=first[0] if first else '',
            market=args.market, out='healthy semantic no_change',
            delivery_state='no_change'), ensure_ascii=False))
    except OSError as exc:
        return input_error(args.market, f'no_change marker 写入失败: {exc}')
    cron_heartbeat.record(args.market, 'no_change',
                          job_name=heartbeat.get('job'), slot=heartbeat.get('slot'),
                          should_alert=False, reasoning_invoked=allow_soft_review,
                          dashboard_published=dashboard_published,
                          data_plane_status=data_plane_status)
    print(json.dumps({
        'status': 'no_change', 'market': args.market, 'mode': 'no_change',
        'wechat_sent': None, 'telegram_sent': None,
        'dashboard_published': dashboard_published,
        'data_plane_status': data_plane_status,
        'heartbeat': {'job': heartbeat.get('job'), 'slot': heartbeat.get('slot'),
                      'state': 'no_change'},
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--text-file',
                        help='report text file (canonical path; stdin only for manual runs)')
    parser.add_argument('--context-id', required=True,
                        help='the context_id printed by intraday_preflight; must equal '
                             'the context on disk. The file holds ONLY the ▎我的看法 '
                             'prose and the harness prepends the data block.')
    args = parser.parse_args(argv)

    # Holiday/weekend gate: no send/publish on a closed market.
    closed = trading_calendar.closed_reason(args.market)
    if closed:
        market_cn = '港股' if args.market == 'hk' else '美股'
        result = {'status': 'market_closed', 'market': args.market, 'reason': closed,
                  'wechat_sent': False, 'wechat_prefix': '',
                  'issues': [f'{market_cn}{closed}，跳过投递+publish']}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    ctx, err = load_context(args.market)
    if ctx is None:
        cron_heartbeat.record(
            args.market, 'postflight_failed', failure_stage='context_load',
        )
        result = {
            'status': 'fail',
            'issues': [err],
            'wechat_prefix': f'🔴 postflight 异常: {err}\n\n',
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    if ctx.get('delivery_mode') == 'no_change':
        return finish_no_change(ctx, args)

    if ctx.get('delivery_mode') == 'review_candidate':
        selection, selection_error = read_report_text(args.market, args.text_file)
        if selection_error:
            return input_error(args.market, selection_error)
        if selection.strip() == 'SILENT':
            return finish_no_change(ctx, args, allow_soft_review=True)

    receipt_only = ctx.get('delivery_mode') == 'unchanged_receipt'
    if receipt_only:
        # No model prose exists on this path.  Requiring a dummy text file would
        # turn the cheapest healthy slot back into tool churn and stale-file risk.
        text, in_err = (ctx.get('raw_wechat_block') or '').strip(), None
    else:
        text, in_err = read_report_text(args.market, args.text_file)
    if in_err:
        return input_error(args.market, in_err)

    # ── Generation gate (prose mode only) ────────────────────────────────────
    # The model echoes the context_id it wrote against. A mismatch means the
    # context on disk was replaced after the prose was written — the agent ran
    # preflight a second time mid-turn. Assembling fresh numbers under stale
    # prose would produce an internally contradictory check-in that LOOKS clean,
    # so refuse to assemble and fall through to the data-block-only path.
    stale_generation = (
        not receipt_only and args.context_id != ctx.get('context_id')
    )

    # Keep the model's own text for the content rules; assemble the delivered
    # body separately, so the prepended block never satisfies a rule on the
    # model's behalf.
    model_text = text
    if receipt_only and not stale_generation:
        text = (ctx.get('raw_wechat_block') or '').strip()
    elif not stale_generation:
        text = assemble_message(ctx, text)

    issues = ([f'context_id 不匹配: 模型基于 {args.context_id}，当前 context 是 '
               f'{ctx.get("context_id")} — 散文与数据不同代，拒绝拼装']
              if stale_generation
              else ([] if receipt_only else validate(text, ctx, model_text)))
    status = 'fail' if stale_generation else categorize(issues)

    # Step 2.5 sidecar liveness (warn-only, stderr — NOT in the WeChat report):
    # the dashboard status banner went dark 06-04→06-10 when a payload rewrite
    # dropped Step 2.5 and nothing noticed for 6 days. A missing narrative
    # sidecar must never block/clutter the report (kcn: no per-cron alerts),
    # but it should leave a visible trace in the cron run log + result JSON.
    sidecar_date = ctx.get('date')
    try:
        datetime.strptime(str(sidecar_date), '%Y-%m-%d')
    except (TypeError, ValueError):
        sidecar_date = datetime.now().strftime('%Y-%m-%d')
    insights_path = TMP / f'intraday-insights-{sidecar_date}.json'
    # A receipt has no new model judgement.  Re-normalizing yesterday's file
    # would stamp old prose with the current UTC time and make it look fresh.
    insights_written = (False if receipt_only else normalize_intraday_insights(
        insights_path, written_after=ctx.get('generated_at')))
    if not insights_written and not receipt_only:
        print(f'warn: {insights_path.name} 缺失或不可用 — dashboard status_banner 将过期隐藏 '
              f'(SKILL Mode 7 Step 2.5 / cron payload Step 2.5)', file=sys.stderr)

    # The banner counts and lists ESCALATING issues only; advisory findings get
    # their own line below, so a truncated list can never drop them (#134).
    escalating, advisories = split_advisory(issues)
    # What shipped, not what the checker noticed — see product_status (#1076).
    product = product_status(status, escalating)
    if status == 'pass' or not escalating:
        banner = ''
    elif status == 'warn':
        # 🟠, not ⚠️: on this card ⚠️ only ever heads the analyzer's signal
        # block (contract §4, one symbol per meaning).
        banner = (f'🟠 校验警告 ({len(escalating)}): '
                  + '; '.join(escalating[:2])
                  + '\n\n')
    else:
        banner = (f'🔴 Validation FAILED ({len(escalating)} issues), 仅发布数据块:\n'
                  + '\n'.join('- ' + i for i in escalating[:4])
                  + '\n\n')
    # Advisory findings keep their own visible line (#134), but at the foot of
    # the card: on top they were the first thing kcn read on a clean slot and
    # looked like an error (2026-09-25). Escalating banners stay on top.
    wechat_prefix = banner
    advisory_suffix = advisory_prefix(advisories).strip()

    # ── WeChat delivery (decoupled from the cron's announce) ──────────────────
    # The cron's announce fires at the END of a long agent turn using a token
    # captured at turn START → expires mid-turn (#61174) → silent drop. We instead
    # send here, in a short-lived `openclaw message send` that grabs a FRESH token
    # (the path kcn confirmed lands when announce didn't). The 3 intraday crons run
    # --no-deliver so this is the SOLE send → no double, no long-turn drop. We
    # record the real send result to a marker so intraday_watchdog only re-sends on
    # a CONFIRMED failure (never doubles a report that went out here).
    wechat_sent = None
    # Why the WeChat leg did not land, when it did not. `wechat_sent=false` is
    # what a health surface counts; without the reason next to it, a channel
    # that is DOWN and a channel that drops one now and then are the same row
    # (#1231 made exactly this argument for the Telegram co-send).
    send_out = ''
    tg_ok = None
    # Set when claim_send refuses this process the send right: it then has no
    # evidence about whether delivery happened and must not file a
    # primary_delivery verdict over the concurrent holder's (#1006).
    send_claim_declined = False
    marker = delivery_receipts.receipt_path(TMP, 'intraday', market=args.market)
    # Idempotency: if openclaw auto-retried this run (post-turn summary-gen failure),
    # the report already went out on the prior attempt — skip the re-send. Intraday's
    # marker is per-market, so use a 20min window (< the 30min slot cadence, > the
    # few-min retry gap) to tell a retry from the next legit slot. See already_delivered.
    # The window is not enough on its own — a slot that landed late leaves a
    # marker still inside it when the next slot's postflight runs — so the
    # marker's slot must also be this context's slot (#1555).
    # WeChat and Telegram are judged separately (2026-09-17): a retry after a slot
    # that landed only Telegram re-sends WeChat alone.
    delivered_this_run = False
    this_slot = (ctx.get('heartbeat') or {}).get('slot')
    _, telegram_done = delivered_channels(
        marker, within_ms=20 * 60 * 1000, slot=this_slot)
    if already_delivered(marker, within_ms=20 * 60 * 1000, slot=this_slot):
        print('idempotency: intraday already delivered this slot — skip re-send', file=sys.stderr)
        wechat_sent = True
        tg_ok = telegram_done
    else:
        # Fail-closed, not silent (#135). A rejected report used to send nothing
        # at all, leaving a market slot indistinguishable from a dead cron until
        # the watchdog mirrored a block to Telegram 10-40 minutes later. Deliver
        # the harness-owned data block instead — every number in it is
        # trustworthy by construction — and drop the prose that failed. Same
        # shape as report_postflight's fail-closed body selection.
        raw_block = (ctx.get('raw_wechat_block', '') or '').strip()
        block_first = raw_block.splitlines()
        block_first = block_first[0] if block_first else ''
        body = raw_block if status == 'fail' else text
        if status == 'fail' and not raw_block:
            # Nothing trustworthy to deliver: the banner alone is the scary empty
            # send this harness already fixed once (2026-06-17). Leave it to the
            # watchdog rather than push a message with no content.
            print('warn: validation failed and the context carries no data block — '
                  'nothing sent, watchdog owns this slot', file=sys.stderr)
        else:
            message = (wechat_prefix + body).strip()
            if advisory_suffix:
                message += '\n\n' + advisory_suffix
            # Same race as #508 on the report path: the marker is written only
            # after both sends return, so a second postflight started inside
            # that window sees "not delivered" and doubles the slot. The claim
            # is taken before the send.
            #
            # Named with this slot (#1742), the same one the marker is matched
            # on (#1555): per-market alone, a claim this slot's crashed sender
            # left behind was indistinguishable from the previous slot's, and
            # the next watchdog announced a WeChat delivery it could not confirm
            # for a send that had never started. The staleness window stays at
            # 20min — shorter than the 30min slot, so a same-slot retry after a
            # dead holder is still arbitrated rather than waiting a full slot.
            claim_path = delivery_receipts.claim_path(
                TMP, 'intraday', market=args.market, slot=this_slot)
            won, claim_reason = claim_send(claim_path, stale_after_ms=20 * 60 * 1000)
            if not won:
                print(f'concurrency: intraday {args.market} send is already claimed '
                      f'({claim_reason}) — not sending a second copy; the watchdog owns '
                      f'this slot if the first one did not land', file=sys.stderr)
                log({'tag': f'intraday-{args.market}', 'action': 'send-claim-declined',
                     'reason': claim_reason})
                wechat_sent, send_out = False, f'send-claim-declined: {claim_reason}'
                send_claim_declined = True
            else:
                mark_send_started(claim_path)
                # WeChat, then Telegram (cold-proof — WeChat can't confirm real
                # delivery), per the delivery policy. The Telegram result is recorded:
                # it's the sole backstop intraday_watchdog uses (no WeChat resend), so
                # it needs to know if TG already got this.
                wechat_sent, send_out, tg_ok = send_per_policy(
                    'intraday', render_for_channel(message, ctx, 'wechat'),
                    tag=f'intraday-{args.market}', market=args.market,
                    wechat=send_wechat, telegram=cosend_telegram,
                    resolve=resolve_wechat_target, telegram_done=telegram_done,
                    telegram_message=render_for_channel(message, ctx, 'telegram'))
                delivered_this_run = bool(wechat_sent or tg_ok)
                # Only the process that actually sent may write the marker. A
                # declined claim writing one would tell intraday_watchdog this
                # slot was handled while nothing went out (#508).
                marker_written = False
                try:
                    safe_write_text(str(marker), json.dumps(delivery_marker_payload(
                        ctx,
                        ts=int(datetime.now().timestamp() * 1000),
                        sent_ok=wechat_sent,
                        tg_ok=tg_ok,
                        first_line=block_first,
                        market=args.market,
                        out=send_out,
                        delivery_state='failed' if status == 'fail' else 'delivered',
                    ), ensure_ascii=False))
                    marker_written = True
                except Exception as e:
                    print(f'warn: marker write failed: {e}', file=sys.stderr)
                # The marker owns idempotency from here — but only if it exists.
                # Released without one, openclaw's retry would send this slot a
                # second time (#1743). Keeping it costs nothing a later slot
                # needs: since #1742 the claim carries this slot, so it refuses
                # a re-send of THIS slot and no other.
                release_claim(claim_path, marker_written=marker_written)
                if not wechat_sent:
                    print(f'warn: WeChat send failed (watchdog will retry): {send_out[:200]}',
                          file=sys.stderr)

    # A failed generation delivers the deterministic block so the slot remains
    # visible, but it has not delivered the intended semantic report.  Keep the
    # old cursor so the next slot retries the full delta instead of collapsing
    # it into an unchanged receipt.
    if delivered_this_run and status != 'fail':
        try:
            intraday_delta.persist_delivered_state(WS, ctx)
        except OSError as exc:
            print(f'warn: intraday delivered-state write failed: {exc}', file=sys.stderr)

    raw_block = (ctx.get('raw_wechat_block', '') or '').strip()
    data_plane_ready = ctx.get('status') == 'ok' and bool(raw_block)
    if data_plane_ready:
        data_plane_status, dashboard_published = publish_data_plane(args.market)
    else:
        data_plane_status, dashboard_published = 'unavailable', False

    result = {
        'status':        status,
        'market':        args.market,
        'mode':          'unchanged_receipt' if receipt_only else 'prose',
        'time':          datetime.now().strftime('%H:%M'),
        'issues':        issues,
        'wechat_prefix': wechat_prefix,
        'n_chars':       len(text),
        'n_chars_model': len(model_text) if model_text is not None else len(text),
        'wechat_sent':   wechat_sent,
        'telegram_sent': tg_ok,
        'dashboard_published': dashboard_published,
        'data_plane_status': data_plane_status,
        'narrative_status': {
            'pass': 'success', 'warn': 'warning', 'fail': 'failed',
        }[product],
        'insights_sidecar': insights_written,
    }
    heartbeat = ctx.get('heartbeat') or {}
    publication_ok = data_plane_status in {'published', 'current'}
    if data_plane_ready and publication_ok:
        heartbeat_state = 'completed'
    elif data_plane_ready:
        heartbeat_state = 'publish_failed'
    else:
        heartbeat_state = 'postflight_failed'
    cron_heartbeat.record(
        args.market,
        heartbeat_state,
        job_name=heartbeat.get('job'), slot=heartbeat.get('slot'),
        postflight_status=product, wechat_sent=wechat_sent,
        # Only when it failed: a reason field on a send that worked is noise in
        # a record read by eye, and the same rule the co-send log follows.
        wechat_detail=(send_out or 'no output from the transport')[-200:]
        if wechat_sent is False else None,
        telegram_sent=tg_ok, dashboard_published=dashboard_published,
        data_plane_status=data_plane_status,
        insights_sidecar=insights_written, issue_count=len(issues),
        # Published so a gate that runs elsewhere can see a lane only this
        # machine can measure: commits made here that never reached the remote
        # (#1241). `None` when it cannot be determined — never 0.
        unpushed_commits=cron_heartbeat.unpushed_commits(),
        # The ledger needs the same escalating/advisory split the banner uses:
        # an advisory-only slot delivered a clean report (#764).
        escalating_count=len(escalating), advisory_count=len(advisories),
        # None is dropped by record(): only a genuine decline carries the flag
        # that tells the outcome bridge this process holds no delivery verdict.
        send_claim_declined=send_claim_declined or None,
    )
    result['heartbeat'] = {
        'job': heartbeat.get('job'), 'slot': heartbeat.get('slot'),
        'state': heartbeat_state,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not publication_ok:
        return 2
    return postflight_exit_code(product)


if __name__ == '__main__':
    sys.exit(main())
