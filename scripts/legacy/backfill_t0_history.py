#!/usr/bin/env python3
"""一次性回填 t0_setups_history.jsonl —— 用 memory/snapshots/ 里的历史每日快照重建牌面，
让 t0_setup_review 的数据背书「现在就有」而不必等数周累积。零网络。

每个快照含当日 day_high/day_low/current_price，足够算 range_pos → grade()。
ATR 历史值无法回溯（quant 当时未必算），range_used_atr 缺省 None——grade() 已能靠
区间位本身判追高（rp≥85 / rp≥70 分档）。settle 仍由 t0_setup_review 按相邻交易日做。

幂等：重跑会按 (date,ticker) 去重覆盖（review 端去重），但为干净起见本脚本直接重写
仅含 backfill 的行 + 保留任何已有 live 行。默认 dry-run，--write 才落盘。
"""
import json
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
SNAP_DIR = WS / 'memory' / 'snapshots'
HIST = WS / 'assets' / 'data' / 't0_setups_history.jsonl'

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
import compute_t0_setups as t0  # noqa: E402

SNAP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\.json$')


def main(argv):
    write = '--write' in argv
    files = sorted(p for p in SNAP_DIR.glob('*.json') if SNAP_RE.match(p.name))
    lines = []
    for f in files:
        d = f.stem  # YYYY-MM-DD
        try:
            snap = json.loads(f.read_text())
        except Exception:
            continue
        rows = {}
        for region, port in snap.get('portfolios', {}).items():
            market = t0._market_of(region)
            for h in port.get('holdings', []):
                if (t0._num(h.get('shares')) or 0) <= 0:
                    continue
                m = t0.holding_metrics(h)        # 无 quant ATR → 靠区间位判
                if m.get('current') is None or m.get('range_pos') is None:
                    continue
                _, label, _ = t0.grade(m)
                rows[h.get('ticker')] = {'grade_label': label,
                                         'range_pos': m['range_pos'],
                                         'close': m['current'], 'market': market}
        if rows:
            lines.append(json.dumps({'as_of': d, 'ts': f'{d}T16:00:00+08:00',
                                     'rows': rows, 'backfill': True}, ensure_ascii=False))

    print(f'回填 {len(lines)} 个交易日（来自 {len(files)} 个快照）')
    # 牌面分布速览
    from collections import Counter
    c = Counter()
    for ln in lines:
        for t, m in json.loads(ln)['rows'].items():
            c[m['grade_label']] += 1
    for lab, n in c.most_common():
        print(f'  {lab}: {n} 次')

    if not write:
        print('\n(dry-run — 加 --write 落盘)')
        return 0

    # 保留已有的非 backfill（live）行，避免覆盖真实留痕
    live = []
    if HIST.exists():
        for ln in HIST.read_text().splitlines():
            if ln.strip():
                try:
                    if not json.loads(ln).get('backfill'):
                        live.append(ln)
                except Exception:
                    pass
    HIST.parent.mkdir(parents=True, exist_ok=True)
    HIST.write_text('\n'.join(lines + live) + '\n')
    print(f'\n✓ 写入 {HIST}（{len(lines)} backfill + {len(live)} live 行）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
