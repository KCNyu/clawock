#!/usr/bin/env python3
"""
KCNyu off-host brief fallback, called by the repository workflow.

Single-turn vendor call (MiniMax M3 primary, optional opencode-go fallback) to generate
today's brief if openclaw cron failed to produce one by the 08:25 HKT check. Reads
brief-context-{date}.json from preflight, writes pre-open.md + plan.json.

Env: MINIMAX_API_KEY required; OPENCODE_API_KEY optional fallback
"""
import json
import os
import re
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

from clawock.automation.llm import chat
from clawock.decision import ledger as decision_v2

# Output budget for the single-turn brief. Thinking is enabled, and _call_provider
# takes its reasoning budget out of this same allowance, so the usable prose budget is
# BRIEF_MAX_TOKENS minus up to 16000. Sized against the real artifact: briefs run ~33KB
# (~20K tokens) plus the trailing plan.json block, so this leaves roughly 4x headroom
# and stays well under MiniMax M3's 131072 cap. See the call site for why 32000 failed.
BRIEF_MAX_TOKENS = 96000


def split_brief_and_plan(out):
    """(markdown, plan_json_str) from the model output.

    The plan is the LAST valid JSON object in the output. _extract_last_json finds
    it regardless of fence case/spacing, an EARLIER ```json example, or unbalanced
    braces in the prose — the exact lowercase ` ```json ` split discarded a valid
    plan the moment the model shifted case/spacing, defeating the last automatic
    brief-recovery path (2026-07 audit). Markdown = everything before the plan,
    with a trailing ```json/``` fence trimmed. A wrong grab is still rejected
    downstream by plan schema validation, so this never publishes junk.
    """
    plan, start = _extract_last_json(out)
    if start is None:
        return out, '{}'
    md = out[:start]
    md = re.sub(r'```[ \t]*json\b[ \t]*\n?$', '', md, flags=re.IGNORECASE)
    return md.rstrip().rstrip('`').rstrip(), plan


def _extract_last_json(text):
    """(last_valid_top_level_JSON_object_str, start_index) or ('{}', None).

    Uses json.raw_decode at each '{', keeping the LAST that parses — so it is
    string-aware (braces inside JSON strings are handled by the decoder), skips an
    earlier ```json example, and is immune to unbalanced braces in the surrounding
    prose (a hand-rolled depth counter is not — an unmatched '{' in Markdown
    poisons it; 2026-07 review)."""
    decoder = json.JSONDecoder()
    last, last_start = '{}', None
    idx = 0
    while True:
        b = text.find('{', idx)
        if b == -1:
            break
        try:
            _, end = decoder.raw_decode(text, b)
        except json.JSONDecodeError:
            idx = b + 1
            continue
        last, last_start = text[b:end], b
        idx = end
    return last, last_start

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
            if name not in REQUIRED_SECTIONS and name != 'portfolio'
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


def main():
    today = (os.environ.get('TODAY') or date.today().isoformat()).strip()
    ctx_path = Path(f'memory/.tmp/brief-context-{today}.json')
    if not ctx_path.exists():
        print(f'FATAL: no preflight context at {ctx_path}', file=sys.stderr)
        sys.exit(1)
    prepared = prepare_context(ctx_path.read_text())
    if not prepared['complete']:
        md, plan = fail_closed_artifacts(today, prepared)
        Path(f'memory/{today}-pre-open.md').write_text(md)
        Path(f'memory/{today}-plan.json').write_text(
            json.dumps(plan, ensure_ascii=False, indent=2))
        print('  fail-closed: required context incomplete; wrote zero-action artifacts')
        return
    context = prepared['serialized']

    skill = Path('skills/daily-deep-brief/SKILL.md').read_text()
    soul = Path('SOUL.md').read_text()
    bootstrap = Path('BOOTSTRAP.md').read_text()

    system = f"You are Rick, kcn's stock analyst. {soul[:1000]}\n\n{bootstrap[:2000]}"
    user = (
        f"按下面 SKILL.md 规则跑 daily-deep-brief, 输出完整 markdown + 末尾 ```json``` block 给 plan.json schema.\n\n"
        f"SKILL.md:\n{skill}\n\n"
        f"Preflight context (deterministic data, 数字以此为准；含 section manifest):\n"
        f"```json\n{context}\n```\n\n"
        f"格式: 1) 完整 brief markdown (按 SKILL); 2) 末尾 ```json``` plan.json. 直接出 brief, 不要客套."
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
    stats = {}
    out = chat(system=system, user=user, max_tokens=BRIEF_MAX_TOKENS,
               temperature=0.6, timeout=900, stats_out=stats)
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

    # Split markdown + plan.json (see split_brief_and_plan for the tolerance rules).
    md_part, json_part = split_brief_and_plan(out)

    desc = (f"clawock 盘前深度简报 {today}：港股 + 美股真实持仓的多空辩论、量化因子、"
            f"风控硬闸与 AI 自评战绩（诚实公开，主动建议平均方向分为负）。")
    md_with_fm = (
        f"---\nlayout: default\ntitle: 盘前深度简报 · {today} (off-host fallback)\n"
        f'description: "{desc}"\n---\n\n'
        + md_part.strip()
    )

    # VALIDATE BEFORE WRITING ANYTHING (2026-07-16). This used to write pre-open.md
    # first and validate after, so a vendor that returns 200 with junk (MiniMax does:
    # 2026-07-16 gave "121 in / 80 out (stop=end_turn)" then failed validation) left a
    # junk pre-open.md on disk. Two ways that bites: the repo's publish cron sweeps
    # memory/ every 20 min and would commit it, and brief-fallback.yml's own skip gate
    # keys on pre-open.md existing — one junk file and every later fallback self-skips.
    # Nothing may touch memory/ until the plan is known good.
    try:
        plan = json.loads(json_part)
    except Exception as e:
        raise SystemExit(f'plan.json parse failed: {e}')
    if 'actions' in plan:
        raise SystemExit('LLM returned forbidden v1 actions field')
    plan['date'] = plan.get('date') or today
    if prepared['payload'].get('generation_id'):
        plan['context_generation_id'] = prepared['payload']['generation_id']
    plan = decision_v2.normalize_authored_plan(plan)
    errors = decision_v2.validate_plan(plan)
    if errors:
        raise SystemExit('plan.json v2 validation failed: ' + '; '.join(errors))
    Path(f'memory/{today}-pre-open.md').write_text(md_with_fm)
    Path(f'memory/{today}-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f'  wrote pre-open.md + plan.json ({len(plan.get("decisions", []))} decisions)')


if __name__ == '__main__':
    main()
