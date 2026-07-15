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


def main():
    today = (os.environ.get('TODAY') or date.today().isoformat()).strip()
    ctx_path = Path(f'memory/.tmp/brief-context-{today}.json')
    if not ctx_path.exists():
        print(f'FATAL: no preflight context at {ctx_path}', file=sys.stderr)
        sys.exit(1)
    context = ctx_path.read_text()

    skill = Path('skills/daily-deep-brief/SKILL.md').read_text()
    soul = Path('SOUL.md').read_text()
    bootstrap = Path('BOOTSTRAP.md').read_text()

    system = f"You are Rick, kcn's stock analyst. {soul[:1000]}\n\n{bootstrap[:2000]}"
    user = (
        f"按下面 SKILL.md 规则跑 daily-deep-brief, 输出完整 markdown + 末尾 ```json``` block 给 plan.json schema.\n\n"
        f"SKILL.md:\n{skill}\n\n"
        f"Preflight context (deterministic data, 数字以此为准):\n```json\n{context[:30000]}\n```\n\n"
        f"格式: 1) 完整 brief markdown (按 SKILL); 2) 末尾 ```json``` plan.json. 直接出 brief, 不要客套."
    )

    # Use full mimo-v2.5-pro cap (32K) + thinking enabled for brief depth
    out = chat(system=system, user=user, max_tokens=32000, temperature=0.6)

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
    Path(f'memory/{today}-pre-open.md').write_text(md_with_fm)

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
    Path(f'memory/{today}-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f'  wrote pre-open.md + plan.json ({len(plan.get("decisions", []))} decisions)')


if __name__ == '__main__':
    main()
