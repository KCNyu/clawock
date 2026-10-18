"""Read-only research context and deterministic card; never a live signal source."""
from datetime import datetime, timezone
import json
import math

STATUSES = {'blocked_data_rights', 'insufficient_or_failed', 'retrospective_candidate',
            'synthetic_test_only'}
LABELS = {'blocked_data_rights': '数据研究权限未核实', 'insufficient_or_failed': '样本或净验证未通过',
          'retrospective_candidate': '仅历史候选，未前瞻验证', 'synthetic_test_only': '合成测试，非实证',
          'missing': '无本市场验证记录', 'invalid': '研究回执无效'}


def _text(value, limit=160):
    return ' '.join(str(value or '未知').split())[:limit]


def snapshot(workspace, market, *, now=None):
    now = now or datetime.now(timezone.utc)
    empty = {'validation': 'missing', 'live_permission': False, 'market': market,
             'source': {}, 'as_of': None, 'metrics': {}, 'focus': 'validation'}
    path = workspace / 'memory/.tmp/intraday-research-latest.json'
    if not path.exists():
        path = workspace / 'config/intraday-research-status.json'
    try:
        if path.stat().st_size > 20_000_000:
            raise ValueError('oversized research receipt')
        report = json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        if report.get('schema') != 'intraday-research/v1' or report.get('live_permission') is not False:
            raise ValueError('invalid authority contract')
        if report.get('validation') not in STATUSES:
            raise ValueError('unknown validation state')
        if report.get('market') != market:
            return empty
        stamp = datetime.fromisoformat(report['generated_at'])
        if stamp.utcoffset() is None or stamp > now:
            raise ValueError('invalid generation timestamp')
        source = report['source']
        public = source.get('derived_public_use') is True and source.get('research_use') is True
        metrics = {}
        if public:
            for name, row in report.get('metrics', {}).items():
                if name not in {'base', 'hold', 'fixed_band', 'simple_regime', 'llm', 'spread_x2',
                                'delay_one_bar', 'unknown_fee_2bps', 'regular_taf'}:
                    raise ValueError('unknown arm')
                metrics[name] = {key: row.get(key) for key in ('net_increment', 'max_session_close_drawdown', 'costs', 'trades')}
                for value in metrics[name].values():
                    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                        raise ValueError('invalid research metric')
        focus = report.get('manifest', {}).get('presentation_focus', 'validation')
        if focus not in ('validation', 'costs', 'path'):
            raise ValueError('invalid emphasis')
        replay = report.get('last_replay') or {}
        # A compact reference to the receipt, not raw history or future prices.
        trace, economics = [], None
        if public:
            for trade in replay.get('trades', [])[:1]:
                trace = [trade.get('signal_at'), trade.get('entry_bar_end'), trade.get('exit_bar_end')]
                qty, entry = trade['shares'], trade['sell_price']
                net = trade['net_pnl']
                charge = trade['sell_cost']['total'] + trade['buy_cost']['total']
                if any(type(v) not in (int, float) or not math.isfinite(v) for v in (qty, entry, net, charge)) or qty <= 0 or entry <= 0:
                    raise ValueError('invalid trade receipt')
                economics = {'net_bps': net/(qty*entry)*10000, 'cost_bps': charge/(qty*entry)*10000,
                             'sleeve_shares': qty, 'base_shares': report['manifest']['base_shares']}

        return {**empty, 'validation': report['validation'], 'ticker': report.get('ticker'),
                'source': {key: source.get(key) for key in ('provider', 'url', 'retrieved_at')},
                'as_of': report.get('as_of'), 'generated_at': report['generated_at'],
                'report_age_hours': round((now-stamp).total_seconds()/3600, 1),
                'historical_only': True, 'metrics': metrics, 'focus': focus, 'trace': trace, 'economics': economics,
                'manifest_sha256': report.get('manifest_sha256'),
                'metrics_withheld_for_rights': not public,
                'blockers': report.get('blockers', []), 'llm_missing_or_invalid': len(report.get('llm_errors', [])),
                'prospective_status': report.get('prospective_status', 'not_started')}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {**empty, 'validation': 'invalid'}


def render(ctx):
    """Harness owns every number; emphasis can reorder detail but hide nothing."""
    status = LABELS.get(ctx.get('validation'), LABELS['invalid'])
    source = ctx.get('source') or {}
    lines = ['▎策略研究 · 非实盘指令', status,
             f"来源：{_text(source.get('provider'))}｜数据截至：{_text(ctx.get('as_of'))}"]
    if source.get('retrieved_at'):
        lines.append(f"采集：{_text(source['retrieved_at'])}｜历史样本，不是实时信号")
    if ctx.get('generated_at'):
        lines.append(f"验证回执：{_text(ctx['generated_at'])}｜距本档 {ctx['report_age_hours']:.1f} 小时")
    if ctx.get('metrics_withheld_for_rights'):
        lines.append('无可公开展示的授权净绩效；不显示成交价或动作。')
    if ctx.get('blockers'):
        lines.append('缺口：' + '；'.join(_text(x, 100) for x in ctx['blockers'][:2]))
    currency = 'HKD' if ctx.get('market') == 'hk' else 'USD'
    metrics = ctx.get('metrics') or {}
    order = list(metrics)
    if ctx.get('focus') == 'costs':
        order.sort(key=lambda name: name != 'spread_x2')
    for name in order:
        row = metrics[name]
        def num(key):
            value = row.get(key)
            return '未知' if value is None else f'{value:.2f}'
        lines.append(f"{name} 净增量 {num('net_increment')} {currency}｜场次末回撤 {num('max_session_close_drawdown')}｜成本 {num('costs')}")
    if metrics:
        lines.append('净增量相对保留底仓，不是账户总回报；费用按当前税表反事实、月度额度内情景。')
    if ctx.get('trace'):
        lines.append('历史模拟路径（非今天）：' + ' → '.join(_text(x, 40) for x in ctx['trace']))
    economics = ctx.get('economics')
    if economics:
        # Same scale; cap only glyph count and retain exact numeric labels.
        for label, key in [('最近历史回转净增量', 'net_bps'), ('往返费用', 'cost_bps')]:
            value = economics[key]
            bar = '▮' * min(20, int(abs(value)/5))
            lines.append(f'{label} {value:+.2f} bps {bar}（每格5bps，最多20格）')
        lines.append(f"研究底仓 {economics['base_shares']} 股｜回转 {economics['sleeve_shares']} 股；不是今日建议尺寸")
    lines.append('前瞻验证未完成；live/SPCH 权限不变。')
    return '\n'.join(lines)
