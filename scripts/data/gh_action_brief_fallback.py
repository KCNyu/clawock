#!/usr/bin/env python3
"""
gh_action_brief_fallback.py — called by .github/workflows/brief-fallback.yml.

Single-turn vendor call (MiniMax M3 primary, optional Xiaomi fallback) to generate
today's brief if openclaw cron failed to produce one by the 08:25 HKT check. Reads
brief-context-{date}.json from preflight, writes pre-open.md + plan.json.

Env: MINIMAX_API_KEY required; XIAOMI_API_KEY optional fallback
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xiaomi_llm import chat
import decision_v2

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


def main():
    today = (os.environ.get('TODAY') or date.today().isoformat()).strip()
    ctx_path = Path(f'memory/.tmp/brief-context-{today}.json')
    if not ctx_path.exists():
        print(f'FATAL: no preflight context at {ctx_path}', file=sys.stderr)
        sys.exit(1)
    # Re-serialize compact. Preflight writes the context pretty-printed, which is 194KB
    # on disk but 116KB as one line — 40% of the prompt was indentation, and under the
    # old character cap that whitespace was displacing real data.
    context = ctx_path.read_text()
    try:
        context = json.dumps(json.loads(context), ensure_ascii=False, separators=(',', ':'))
    except Exception:
        pass  # malformed context: send it raw and let the LLM/validator complain

    skill = Path('skills/daily-deep-brief/SKILL.md').read_text()
    soul = Path('SOUL.md').read_text()
    bootstrap = Path('BOOTSTRAP.md').read_text()

    system = f"You are Rick, kcn's stock analyst. {soul[:1000]}\n\n{bootstrap[:2000]}"
    user = (
        f"按下面 SKILL.md 规则跑 daily-deep-brief, 输出完整 markdown + 末尾 ```json``` block 给 plan.json schema.\n\n"
        f"SKILL.md:\n{skill}\n\n"
        f"Preflight context (deterministic data, 数字以此为准):\n```json\n{context[:CONTEXT_CAP]}\n```\n\n"
        f"格式: 1) 完整 brief markdown (按 SKILL); 2) 末尾 ```json``` plan.json. 直接出 brief, 不要客套."
    )

    # Use full mimo-v2.5-pro cap (32K) + thinking enabled for brief depth.
    # timeout=900: the full-context brief prefills ~116KB and thinks before emitting
    # ~20K tokens; the 180s default timed out 3x on 2026-07-16 and killed the run.
    out = chat(system=system, user=user, max_tokens=32000, temperature=0.6, timeout=900)

    # Split markdown + plan.json
    if '```json' in out:
        md_part, json_part = out.rsplit('```json', 1)
        json_part = json_part.split('```', 1)[0].strip()
    else:
        md_part = out
        json_part = '{}'

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
    plan = decision_v2.normalize_authored_plan(plan)
    errors = decision_v2.validate_plan(plan)
    if errors:
        raise SystemExit('plan.json v2 validation failed: ' + '; '.join(errors))
    Path(f'memory/{today}-pre-open.md').write_text(md_with_fm)
    Path(f'memory/{today}-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f'  wrote pre-open.md + plan.json ({len(plan.get("decisions", []))} decisions)')


if __name__ == '__main__':
    main()
