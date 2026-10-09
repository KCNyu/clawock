#!/usr/bin/env python3
"""
KCNyu off-host brief fallback, called by the repository workflow.

Single-turn vendor call (MiniMax M3, no second provider) to generate today's brief
if openclaw cron failed to produce one by the 08:25 HKT check. Reads the preflight
context and decision packet of today's generation and writes what the host brief
writes: plan.json and the judgment overlay. The report and the card are rendered
from those by the harness (`clawock brief postflight`), as on the host.

Env: MINIMAX_API_KEY required
"""
import hashlib
import json
import os
import re
import sys
import time
from copy import deepcopy

from clawock import sessions
from clawock.automation.llm import chat
from clawock.automation.llm import DEADLINE_ENV
from clawock.decision import ledger as decision_v2
from clawock.decision import packet as decision_packet
from clawock.safe_io import safe_write_json, safe_write_text
from clawock.workspace import workspace_root

# Output budget for the single-turn brief. Thinking is enabled, and _call_provider
# takes its reasoning budget out of this same allowance, so the usable prose budget is
# BRIEF_MAX_TOKENS minus up to 16000. Sized when the reply was a ~33KB markdown brief
# (~20K tokens) plus a plan block; the plan + judgment JSON it is now is no larger, so
# this still leaves roughly 4x headroom and stays well under MiniMax M3's 131072 cap.
# See the call site for why 32000 failed.
BRIEF_MAX_TOKENS = 96000
BRIEF_LLM_TIMEOUT_SECONDS = 900

#: What the single turn is told on top of the skill. The skill is an interactive
#: manual: it has the model query tools, write files and run postflight. Handing
#: it over with "output markdown + a plan block" — the contract until #2817 —
#: asked for artifacts the skill forbids and omitted the judgment postflight
#: requires, so a perfect reply still failed the next step. Every place the two
#: differ is resolved here, once, in the direction of the skill's own artifacts.
SINGLE_TURN_ADAPTER = """你在离机兜底环境里单轮生成今天的盘前深度简报：没有任何工具，不能查询、不能写文件、不能跑命令。
分析方法、plan 的 schema（Step 4 的 B）和 judgment 的字段规则（Step 4 的 C）以下面的 SKILL.md 为准；SKILL.md 里凡是要求调用工具、查询 packet、读写文件或跑 preflight/postflight 的地方，在这里一律按下面三条执行：
1. 输入已经全部内联：本次 generation 的 decision packet（SKILL 所说的 summary 与逐票查询的全部内容）和完整 preflight context。数字只取自这两份，取不到就写进 data_holes，不要编。
2. 只输出一个 JSON 对象：{"plan": {...}, "judgment": {...}}。不要输出 markdown 报告、微信卡、insights 或任何客套话——报告与微信卡由 harness 从 plan 和 judgment 渲染。
3. judgment 以下面的「judgment 模板」为骨架原样填空：不增删键，不改 ticker 列表、schema_version 与 context_generation_id；文字字段是纯文本，不含 |、#、**、```、▎，行首不带列表符或引用符。
4. plan 的动作边界与两类买腿按 SKILL.md 的风控「换仓的买腿怎么写」及 Step 4 B 的 add 规则执行；所需的 `constraints`、`technical` 已在内联 packet 中。持仓外的标的（stock_discovery、watch_list）不进 decisions。"""


def _json_objects(text):
    """Every top-level JSON object in `text`, in order.

    `raw_decode` at each '{' is string-aware (braces inside JSON strings are the
    decoder's problem) and immune to an unmatched '{' in surrounding prose — a
    hand-rolled depth counter is not (2026-07 review).
    """
    decoder = json.JSONDecoder()
    found, idx = [], 0
    while True:
        start = text.find('{', idx)
        if start == -1:
            return found
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(value, dict):
            found.append(value)
        idx = end


def split_plan_and_judgment(out):
    """(plan, judgment) from the model's reply.

    Asked for as one object `{"plan", "judgment"}`. The first real reply under
    that contract (rehearsal 2026-10-09) was 31K tokens and was not that shape,
    so the two halves are also accepted as separate objects, wrapped or bare:
    the last object carrying each wins, as the last plan block always has. A
    fence, a preamble or an unbalanced brace in surrounding prose does not lose
    a good reply. Raises ValueError, naming the shapes it did find, before a
    file is written; a wrong grab is still rejected downstream by the plan
    schema and the judgment overlay check.
    """
    plan = judgment = None
    objects = _json_objects(out)
    for value in objects:
        if isinstance(value.get('plan'), dict):
            plan = value['plan']
        elif isinstance(value.get('decisions'), list):
            plan = value
        if isinstance(value.get('judgment'), dict):
            judgment = value['judgment']
        elif isinstance(value.get('ticker_judgments'), list):
            judgment = value
    if plan is None or judgment is None:
        shapes = [sorted(value)[:6] for value in objects[-4:]]
        raise ValueError(
            'model reply must carry a "plan" object and a "judgment" object; '
            f'found {len(objects)} JSON object(s), the last with keys {shapes}')
    return plan, judgment


# Send the WHOLE preflight context. This was context[:30000] until 2026-07-16 — a cap
# sized for an older, smaller context that had since grown to 194KB, so the brief got
# 15% of its data and was cut off mid-`us_stocks`. It then wrote a brief that named the
# missing fields itself and still issued "must act today" calls on 4 positions while
# guessing "HK leg 数据缺失（预判空仓或未刷）" — i.e. blind to the entire HK book.
# Nobody caught it because this path had never once run to completion (see
# dispatch_brief_fallback in _watchdog_common for the two defects that masked it).
# MiniMax M3 takes 1M context and accepted the full body at 23.9K input tokens, so the
# cap only needs to be a sanity bound, not a budget.
CONTEXT_CAP = 400_000
REQUIRED_SECTIONS = ('portfolio', 'hk_stocks', 'us_stocks')
PROTECTED_FIELDS = ('date', 'generation_id')
# Least decision-critical first.  These sections may contain long prose copied
# from feeds; deterministic portfolio state is never placed in this list.
TRIMMABLE_SECTIONS = (
    'news', 'em_news', 'sentiment', 'influencer', 'retrospective',
    'reflections', 'peer_scan', 'us_fundamentals', 'macro', 'catalysts',
)


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _required_section(context, name):
    if name == 'portfolio':
        return context.get('portfolio')
    direct = context.get(name)
    if direct is not None:
        return direct
    portfolio = context.get('portfolio')
    if not isinstance(portfolio, dict):
        return None
    return ((portfolio.get('portfolios') or {}).get(name))


def prepare_context(raw_context, cap=CONTEXT_CAP):
    """Parse and structurally trim context; never cut a serialized JSON string.

    Returns a dict with the compact JSON, parsed payload, manifest and completeness
    decision.  Logical HK/US sections live inside ``portfolio.portfolios`` in the
    current preflight schema, but are reported separately in the manifest because
    they are independently required for safe cross-market advice.
    """
    try:
        original = json.loads(raw_context) if isinstance(raw_context, str) else deepcopy(raw_context)
    except Exception as e:
        manifest = {
            name: {'status': 'missing', 'required': True}
            for name in REQUIRED_SECTIONS
        }
        return {
            'payload': {},
            'serialized': '{}',
            'manifest': manifest,
            'complete': False,
            'errors': [f'context JSON 无法解析: {e}'],
        }
    if not isinstance(original, dict):
        return {
            'payload': {},
            'serialized': '{}',
            'manifest': {
                name: {'status': 'missing', 'required': True}
                for name in REQUIRED_SECTIONS
            },
            'complete': False,
            'errors': ['context 顶层不是 object'],
        }

    payload = deepcopy(original)
    manifest = {}
    errors = []
    for name in REQUIRED_SECTIONS:
        value = _required_section(original, name)
        present = isinstance(value, dict)
        manifest[name] = {
            'status': 'included' if present else 'missing',
            'required': True,
            'bytes': len(_compact(value)) if present else 0,
        }
        if not present:
            errors.append(f'必需 section 缺失: {name}')

    for name in payload:
        if name not in manifest:
            manifest[name] = {
                'status': 'included',
                'required': False,
                'bytes': len(_compact(payload[name])),
            }

    def serialize_with_manifest():
        candidate = deepcopy(payload)
        candidate['_section_manifest'] = manifest
        return candidate, _compact(candidate)

    candidate, serialized = serialize_with_manifest()
    if len(serialized) > cap:
        for name in TRIMMABLE_SECTIONS:
            if name not in payload:
                continue
            before = len(_compact(payload[name]))
            payload[name] = {
                '_trimmed': True,
                'reason': 'context_cap',
                'original_bytes': before,
            }
            manifest[name].update({
                'status': 'trimmed',
                'bytes_before': before,
                'bytes': len(_compact(payload[name])),
            })
            candidate, serialized = serialize_with_manifest()
            if len(serialized) <= cap:
                break

    # If optional structured sections still make the payload too large, omit the
    # largest non-required sections as whole JSON values.  Required state remains
    # byte-for-byte equal to the parsed input.
    if len(serialized) > cap:
        optional = [
            (len(_compact(value)), name)
            for name, value in payload.items()
            if name not in REQUIRED_SECTIONS and name not in PROTECTED_FIELDS
        ]
        for before, name in sorted(optional, reverse=True):
            payload.pop(name, None)
            manifest[name].update({'status': 'omitted', 'bytes_before': before, 'bytes': 0})
            candidate, serialized = serialize_with_manifest()
            if len(serialized) <= cap:
                break

    if len(serialized) > cap:
        errors.append(
            f'必需 section 保全后仍超过 CONTEXT_CAP ({len(serialized)}>{cap})')

    # Mutation guard: a future refactor must not "solve" the cap by changing a
    # required section.  This also detects accidental loss of nested HK/US legs.
    for name in REQUIRED_SECTIONS:
        before = _required_section(original, name)
        after = _required_section(candidate, name)
        if before != after:
            manifest[name]['status'] = 'trimmed'
            errors.append(f'必需 section 被改写: {name}')
    for name in PROTECTED_FIELDS:
        if name in original and original.get(name) != candidate.get(name):
            manifest[name]['status'] = 'trimmed'
            errors.append(f'受保护字段被改写: {name}')

    return {
        'payload': candidate,
        'serialized': serialized,
        'manifest': manifest,
        'complete': not errors,
        'errors': errors,
    }


def fail_closed_artifacts(today, prepared):
    """Deterministic no-action output for incomplete required data."""
    missing = '；'.join(prepared.get('errors') or ['必需数据不完整'])
    md = (
        f"---\nlayout: default\ntitle: 盘前深度简报 · {today} (数据不完整)\n"
        f"description: \"必需持仓数据不完整；本次不生成交易动作。\"\n---\n\n"
        f"# ⚠️ 数据不完整，本次不生成交易动作\n\n"
        f"{missing}。为避免在港股或美股账本盲区下下单，所有买入、卖出、加减仓动作均已禁止。\n\n"
        f"section manifest：\n```json\n"
        f"{json.dumps(prepared.get('manifest') or {}, ensure_ascii=False, indent=2)}\n```\n"
    )
    plan = {
        'schema_version': 2,
        'date': today,
        'data_complete': False,
        'decisions': [],
        'section_manifest': prepared.get('manifest') or {},
    }
    generation_id = (prepared.get('payload') or {}).get('generation_id')
    if generation_id:
        plan['context_generation_id'] = generation_id
    return md, plan


def build_system_prompt(soul: str, bootstrap: str) -> str:
    """The off-host brief writer's system prompt: both files WHOLE.

    This used to be `{soul[:1000]}\\n\\n{bootstrap[:2000]}` — slice sizes picked
    when the files were smaller and never revisited. On committed 2026-08 text
    the SOUL cut landed right before `## Operating mode (this workspace)`
    ("Have a view, name the trade" / "Cite numbers, not vibes") and kept 39% of
    the file; the BOOTSTRAP cut landed mid-sentence inside C+.2 and dropped C+.3
    risk alerts, B+ research lifecycle and all of C. 输出约束 — the exact
    constraint list postflight validates the fallback's output against
    (#962). Same defect class as #959/#961, one layer up: never slice a
    whole document into a prompt. Both files together are ~7.6KB against a
    400KB context budget, so there is no size pressure to manage — any future
    budget belongs in prepare_context, which trims structurally and declares
    what it dropped.
    """
    return f"You are Rick, kcn's stock analyst. {soul.strip()}\n\n{bootstrap.strip()}"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt_path(root, today):
    return root / 'memory' / '.tmp' / f'brief-fallback-receipt-{today}.json'


def artifact_paths(root, today):
    """What one successful fallback run writes, keyed as the receipt names them."""
    return {
        'plan': root / 'memory' / f'{today}-plan.json',
        'judgment': root / 'memory' / '.tmp' / f'brief-judgment-{today}.json',
    }


def verify_receipt(root, today):
    """(ok, message): did a fallback run in this workspace write today's brief?

    A file existing answers a different question. The weekly rehearsal runs on
    days the primary brief is healthy, so the checkout already carries today's
    pre-open.md; on 2026-10-07 every provider attempt failed and the drill
    still reported "produced 44612 bytes" off that committed file (#2818). The
    receipt is written last, by the run that wrote the plan and the judgment,
    and pins their hashes and the generation they were written against.
    """
    path = receipt_path(root, today)
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return False, 'no receipt: this run did not generate a brief'
    except (OSError, ValueError) as exc:
        return False, f'receipt unreadable: {exc}'
    manifest = root / 'memory' / '.tmp' / f'brief-context-{today}' / 'manifest.json'
    try:
        generation_id = json.loads(manifest.read_text(encoding='utf-8')).get('generation_id')
    except (OSError, ValueError) as exc:
        return False, f'context manifest unreadable: {exc}'
    if receipt.get('context_generation_id') != generation_id:
        return False, (f"receipt is for generation {receipt.get('context_generation_id')}, "
                       f'the context is now {generation_id}')
    sizes = {}
    for name, target in artifact_paths(root, today).items():
        expected = (receipt.get('artifacts') or {}).get(name)
        if not target.is_file() or expected != _sha256(target):
            return False, f'{name} is not the file this run wrote'
        sizes[name] = target.stat().st_size
    return True, ('generation ' + str(generation_id) + ' · '
                  + ' · '.join(f'{name} {size} bytes' for name, size in sizes.items()))


#: The least wall clock worth starting a repair turn with; the first real
#: reply took 188s (2026-10-09 rehearsal).
REPAIR_MIN_SECONDS = 240
#: Real replies have failed twice over — malformed JSON first, then a refused
#: decision in the repaired text — so one turn is not always enough. The
#: budget, not this number, is what usually ends it.
MAX_REPAIR_TURNS = 2


class ReplyRejected(Exception):
    """The reply cannot be written as it stands; the message says why."""


def checked_reply(out, today, packet):
    """(plan, judgment, advisories) ready to write, or `ReplyRejected`.

    Everything postflight would fail the brief for and that this side can see
    is a rejection: the reply's shape, the plan schema, the harness's action
    bounds, a judgment with nothing to render. Judgment overlay findings come
    back as advisories — postflight publishes those as a warning.
    """
    generation_id = (packet.get('_meta') or {}).get('generation_id')
    try:
        plan, judgment = split_plan_and_judgment(out)
    except ValueError as exc:
        raise ReplyRejected(str(exc))
    if 'actions' in plan:
        raise ReplyRejected('plan uses the forbidden v1 `actions` field; use `decisions`')
    plan['date'] = plan.get('date') or today
    plan['context_generation_id'] = generation_id
    try:
        plan = decision_v2.normalize_authored_plan(plan)
    except Exception as exc:  # noqa: BLE001
        raise ReplyRejected(f'plan cannot be normalized: {exc}')
    # The filename is what binds the plan to its date (#1915): `or today` only
    # fills a missing date, and a model-written wrong one would otherwise land
    # as memory/<today>-plan.json and derive every id from the wrong day.
    errors = list(decision_v2.validate_plan(plan, f'memory/{today}-plan.json'))
    errors += decision_packet.validate_plan_constraints(plan, packet)
    if not isinstance(judgment.get('ticker_judgments'), list) or not judgment['ticker_judgments']:
        errors.append('judgment carries no ticker_judgments')
    if errors:
        # Name the rows the errors point at, with the harness facts they have
        # to agree with: `decision[8]` alone tells neither the model in the
        # repair turn nor whoever reads the job log which ticker was refused,
        # and "add requires technical_setup_id" does not say which id. The
        # third real run named SPCX and the repair still left the fields out.
        decisions = plan.get('decisions') if isinstance(plan.get('decisions'), list) else []
        named = sorted({int(index) for index in re.findall(r'decision\[(\d+)\]', ' '.join(errors))})
        rows = []
        for index in named:
            row = decisions[index] if index < len(decisions) else None
            if not isinstance(row, dict):
                continue
            ticker = str(row.get('ticker'))
            facts = (packet.get('tickers') or {}).get(ticker)
            if facts is None:
                rows.append(f"decision[{index}] is {ticker} {row.get('action')}: "
                            'not a holding in the packet, so it cannot be a decision')
                continue
            setups = (facts.get('technical') or {}).get('setups') or []
            constraints = facts.get('constraints') or {}
            rows.append(
                f"decision[{index}] is {ticker} {row.get('action')}: packet allowed_actions="
                f"{_compact(constraints.get('allowed_actions'))}, "
                f"technical.setups={_compact(setups)}, "
                f"swap_mandate={_compact(constraints.get('swap_mandate'))}")
        raise ReplyRejected('; '.join(errors + rows))
    # The two pins are the harness's to write, like the plan's above: the model
    # copying a hash wrong must not cost the day its brief.
    judgment['schema_version'] = decision_packet.JUDGMENT_SCHEMA_VERSION
    judgment['context_generation_id'] = generation_id
    return plan, judgment, decision_packet.validate_judgment_overlay(packet, judgment)


def repair_prompt(user, out, reason):
    """The first prompt, the rejected reply and why — for the one repair turn."""
    return (
        f"{user}\n\n"
        f"你上一次的回复：\n{out}\n\n"
        f"它没有通过写盘前的校验：\n{reason}\n\n"
        "只改被指出的地方，其余内容原样保留，重新输出完整的 "
        '{"plan": {...}, "judgment": {...}} 这一个 JSON 对象。'
        "被点名的 decision：上面列出了该票 packet 的 allowed_actions、technical.setups 与 swap_mandate。"
        "按 SKILL.md 的风控「换仓的买腿怎么写」及 Step 4 B 的 add 规则修正买腿；不要编 setup 或扩大授权。"
    )


def main(argv=None):
    """Generate today's fallback brief; `--verify-receipt` only checks one was written.

    Exit 0 from `--verify-receipt` means a fallback run in this workspace wrote
    today's plan and judgment; it generates nothing.
    """
    argv = sys.argv[1:] if argv is None else argv
    today = (os.environ.get('TODAY') or sessions.hkt_today().isoformat()).strip()
    root = workspace_root()
    if '--verify-receipt' in argv:
        ok, message = verify_receipt(root, today)
        print(message)
        return 0 if ok else 1
    context_relative = f'memory/.tmp/brief-context-{today}.json'
    ctx_path = root / context_relative
    if not ctx_path.exists():
        print(f'FATAL: no preflight context at {context_relative}', file=sys.stderr)
        sys.exit(1)
    # A closed-market sentinel is not an incomplete context — it is a context
    # that says nothing was due. Falling through would hand `fail_closed_artifacts`
    # an empty payload and write a zero-action pre-open.md + plan.json for a day
    # neither market opens, which then reads downstream as "the brief ran and had
    # nothing to say". Exit before writing anything. (brief_watchdog gates the
    # same day and should never dispatch us here; this is the second layer, and
    # a manual `gh workflow run` is exactly how the first one gets bypassed.)
    raw_ctx = ctx_path.read_text()
    try:
        status = json.loads(raw_ctx).get('status')
        if status in {'price_refresh_failed', 'preflight_timeout'}:
            print(f'FATAL: {context_relative} reports {status}', file=sys.stderr)
            sys.exit(1)
        if status == 'market_closed':
            print(f'  skip: {context_relative} is a market_closed sentinel — no brief was due')
            return
    except (ValueError, AttributeError):
        pass  # malformed context is prepare_context's problem, not this gate's

    prepared = prepare_context(raw_ctx)
    if not prepared['complete']:
        md, plan = fail_closed_artifacts(today, prepared)
        safe_write_text(root / 'memory' / f'{today}-pre-open.md', md)
        safe_write_json(root / 'memory' / f'{today}-plan.json', plan)
        print('  fail-closed: required context incomplete; wrote zero-action artifacts')
        return
    context = prepared['serialized']

    # The same generation's packet postflight will validate against. Without it
    # there is no judgment template to fill and nothing to bind the plan to, and
    # postflight would refuse the result anyway (`decision packet 不可用`).
    manifest_path = ctx_path.with_suffix('') / 'manifest.json'
    try:
        packet = decision_packet.read_packet(manifest_path)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f'decision packet unavailable for {today}: {exc}')
    generation_id = (packet.get('_meta') or {}).get('generation_id')

    skill = (root / 'skills/daily-deep-brief/SKILL.md').read_text()
    soul = (root / 'SOUL.md').read_text()
    bootstrap = (root / 'BOOTSTRAP.md').read_text()

    system = build_system_prompt(soul, bootstrap)
    template = json.dumps(decision_packet.judgment_template(packet), ensure_ascii=False)
    user = (
        f"{SINGLE_TURN_ADAPTER}\n\n"
        f"SKILL.md:\n{skill}\n\n"
        f"Decision packet (harness 编译的事实、风险与 action bounds):\n"
        f"```json\n{_compact(packet)}\n```\n\n"
        f"judgment 模板:\n```json\n{template}\n```\n\n"
        f"Preflight context (deterministic data, 数字以此为准；含 section manifest):\n"
        f"```json\n{context}\n```\n\n"
        '只输出 {"plan": {...}, "judgment": {...}} 这一个 JSON 对象。'
    )

    # BRIEF_MAX_TOKENS, not 32000: that old number was mimo-v2.5-pro's cap, left behind
    # when MiniMax M3 became primary on 2026-06-16 (M3 maxOutput is 131072, and chat()
    # now clamps per provider, so a budget above the fallback's cap no longer breaks it).
    # 32000 was not merely conservative, it was fatal: chat() leaves thinking
    # enabled, so _call_provider spends min(max_tokens-1024, 16000) of the SAME output
    # budget on reasoning — half of it — leaving ~16K for prose. The brief runs ~33KB.
    # On 2026-08-11 that produced `102644 in / 32000 out (stop=max_tokens)`: the markdown
    # was truncated mid-body, the trailing ```json``` plan block was never emitted, and
    # validation correctly refused to write anything. Net effect: the only automatic
    # recovery path could not physically emit a complete brief.
    # timeout=900: the full-context brief prefills ~116KB and thinks before emitting
    # ~20K tokens; the 180s default timed out 3x on 2026-07-16 and killed the run.
    def report_chain(stats):
        # C-F3a: one grep-able line saying which leg won and what each cost —
        # before this, the job log had per-attempt token lines but nothing that
        # answered "did the fallback write today's brief, and how slow was it?".
        legs = stats.get('legs') or []
        if legs:
            print('LLM chain: ' + ' | '.join(
                f"{l['provider']} {'OK' if l['ok'] else 'FAIL'} "
                f"attempts={l['attempts']} {l['wall_s']}s"
                + (f" ({l.get('error', '')[:60]})" if not l['ok'] else '')
                for l in legs))

    started = time.monotonic()
    stats = {}
    out = chat(system=system, user=user, max_tokens=BRIEF_MAX_TOKENS,
               temperature=0.6, timeout=BRIEF_LLM_TIMEOUT_SECONDS, stats_out=stats)
    report_chain(stats)

    # VALIDATE BEFORE WRITING ANYTHING (2026-07-16). This used to write pre-open.md
    # first and validate after, so a vendor that returns 200 with junk (MiniMax does:
    # 2026-07-16 gave "121 in / 80 out (stop=end_turn)" then failed validation) left a
    # junk pre-open.md on disk. Two ways that bites: the repo's publish cron sweeps
    # memory/ every 20 min and would commit it, and brief-fallback.yml's own skip gate
    # keys on pre-open.md existing — one junk file and every later fallback self-skips.
    # Nothing may touch memory/ until the plan and the judgment are known usable.
    # Repair turns. The host brief gets this for free — postflight says `fail`,
    # the model fixes the named field and reruns — and a single turn had no
    # equivalent: the first real run of this contract (rehearsal 2026-10-09)
    # lost a whole brief to one `add` decision missing its setup fields. They
    # spend what is left of the job's LLM budget, never a second full one.
    budget = float(os.environ.get(DEADLINE_ENV) or BRIEF_LLM_TIMEOUT_SECONDS)
    for turn in range(MAX_REPAIR_TURNS + 1):
        try:
            plan, judgment, advisories = checked_reply(out, today, packet)
            break
        except ReplyRejected as rejected:
            left = budget - (time.monotonic() - started)
            print(f'  reply rejected: {rejected}')
            if turn == MAX_REPAIR_TURNS:
                raise SystemExit(f'model reply rejected after {turn} repair turn(s): {rejected}')
            if left < REPAIR_MIN_SECONDS:
                raise SystemExit(
                    f'model reply rejected with {left:.0f}s left, no repair turn: {rejected}')
            print(f'  repair turn {turn + 1} ({left:.0f}s left of {budget:.0f}s)')
            stats = {}
            out = chat(system=system, user=repair_prompt(user, out, rejected),
                       max_tokens=BRIEF_MAX_TOKENS, temperature=0.2,
                       timeout=BRIEF_LLM_TIMEOUT_SECONDS, deadline_seconds=left,
                       stats_out=stats)
            report_chain(stats)
    for issue in advisories:
        print(f'  warn: judgment: {issue}')

    # Atomic (#1493): the publish sweep would commit a half-written plan.json.
    # No pre-open.md here: the report is the harness's to render, from these
    # two files, in the postflight step that follows.
    paths = artifact_paths(root, today)
    receipt_path(root, today).unlink(missing_ok=True)
    safe_write_json(paths['plan'], plan)
    safe_write_json(paths['judgment'], judgment)
    safe_write_json(receipt_path(root, today), {
        'date': today,
        'context_generation_id': generation_id,
        'artifacts': {name: _sha256(path) for name, path in paths.items()},
    })
    print(f'  wrote plan.json + judgment '
          f'({len(plan.get("decisions", []))} decisions, generation {generation_id})')


if __name__ == '__main__':
    sys.exit(main())
