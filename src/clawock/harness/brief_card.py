"""The brief's WeChat card: the one composition shared by the primary send and the backstop.

`brief_postflight` sends this card and `brief_watchdog` re-sends it when the
primary send did not land, so both must build it from the same code. It used to
live in `_watchdog_common`, the delivery module. That made the brief's
presentation — which card file wins, the plan fallback, the harness-owned
early-candidate section — a delivery concern, and `brief_render` had to import
the watchdog module just to get the page link. Composition is here now.
Delivery (claim, send, receipt) stays in `_watchdog_common` and
`automation.delivery_receipts`.

Reads only workspace files the brief itself wrote (card file, plan, packet
manifest, Pages contract); no network, no send.
"""
import json

from clawock.scheduling import BRIEF_SLOT_HKT
from clawock.decision.book import plan_totals
from clawock.workspace import workspace_root

WS = workspace_root()


def brief_url(date):
    """The public full-brief link for `date` (memory/{date}-pre-open.md on Pages).

    The site root is the workspace's Pages contract (`config/pages-public.json`
    `site_url`), the same value the Pages artifact is published under. Without
    one the link stays workspace-relative instead of pointing at another desk.
    """
    page = f'memory/{date}-pre-open.html'
    try:
        contract = json.loads((workspace_root() / 'config' / 'pages-public.json').read_text())
        site = str(contract.get('site_url') or '').strip().rstrip('/')
    except (OSError, ValueError, AttributeError):
        site = ''
    return f'{site}/{page}' if site else page


_EARLY_SECTION_HEADER = '▎提前布局候选'
_EARLY_BLOCKER_LABELS = {
    'needs_primary_evidence': '缺一手披露',
    'needs_information_confirmation': '缺独立消息确认',
    'overheated_wait_rebreak': '过热，等回踩再突破',
    'leveraged_requires_validated_evidence': '杠杆代理仅观察',
    'no_20d_breakout': '未突破20日高',
    'no_short_peer_leadership': '短期同业领先不足',
}
_EARLY_STATE_LABELS = {
    'exploration_ready': '可小仓试探',
    'wait_pullback_rebreak': '候选·等回踩再突破',
    'wait_information': '候选·等消息确认',
    'candidate_only': '候选·仅观察',
}


def _brief_decision_packet(today):
    manifest = (WS / 'memory' / '.tmp' / f'brief-context-{today}' / 'manifest.json')
    if not manifest.exists():
        return None
    try:
        from clawock.decision import packet as decision_packet
        return decision_packet.read_packet(manifest)
    except Exception:
        return None


def _early_candidate_section(packet):
    """Compact, harness-owned candidate truth, deduplicated by underlying."""
    if not isinstance(packet, dict):
        return ''
    diagnostics = packet.get('add_alpha_diagnostics') or {}
    candidates = diagnostics.get('candidates') or []
    observed = [
        row for row in candidates
        if (row.get('early_trend') or {}).get('observed')
        or row.get('tier') in {'exploration', 'validated'}
    ]
    by_source = {}
    for row in observed:
        source = str(row.get('source_ticker') or row.get('ticker') or '?')
        current = by_source.get(source)
        # Prefer the directly held underlying over a leveraged/proxy row.
        if current is None or (current.get('is_proxy') and not row.get('is_proxy')):
            by_source[source] = row
    idea_count = len(by_source)
    exploration_count = len({
        str(row.get('source_ticker') or row.get('ticker') or '?')
        for row in observed
        if (row.get('early_trend') or {}).get('exploration_ready')
    })
    allowed_count = sum(bool(row.get('allowed')) for row in candidates)
    lines = [
        _EARLY_SECTION_HEADER,
        f'提示 {idea_count} 个底层机会 · 可小仓试探 {exploration_count} · 当前可加仓 {allowed_count}',
    ]
    ranked = sorted(
        by_source.items(),
        key=lambda item: (
            0 if (item[1].get('early_trend') or {}).get('exploration_ready') else 1,
            item[0],
        ),
    )[:2]
    for source, row in ranked:
        early = row.get('early_trend') or {}
        state = _EARLY_STATE_LABELS.get(
            early.get('state'), early.get('state') or row.get('state') or '候选'
        )
        proxies = sorted({
            str(candidate.get('ticker')) for candidate in observed
            if str(candidate.get('source_ticker') or candidate.get('ticker')) == source
            and candidate.get('is_proxy')
        })
        name = source + (f"（{','.join(proxies)} 映射）" if proxies else '')
        blockers = [
            _EARLY_BLOCKER_LABELS.get(blocker, blocker)
            for blocker in early.get('blockers') or []
            if blocker in _EARLY_BLOCKER_LABELS
        ][:2]
        suffix = f"；{'、'.join(blockers)}" if blockers else ''
        lines.append(f'- {name}: {state}{suffix}')
    if not ranked:
        lines.append('- 暂无确定性提前提示；不是“模型没写”，而是价格/同业条件未同时成立')
    from clawock.market_data.stock_discovery import candidate_lines
    discovery_lines = candidate_lines(packet.get('stock_discovery'))
    if discovery_lines:
        # Part of this owned block: re-injection replaces both queues together.
        lines += [''] + discovery_lines
    return '\n'.join(lines)


def _inject_early_candidate_section(card, packet):
    section = _early_candidate_section(packet)
    if not section:
        return card
    lines = card.splitlines()
    start = next(
        (index for index, line in enumerate(lines)
         if line.strip() == _EARLY_SECTION_HEADER),
        None,
    )
    if start is not None:
        end = start + 1
        while end < len(lines):
            stripped = lines[end].strip()
            if stripped.startswith('▎') or stripped.startswith('📈'):
                break
            end += 1
        lines[start:end] = section.splitlines() + ['']
        return '\n'.join(lines).strip()
    insert = next(
        (index for index, line in enumerate(lines)
         if line.strip().startswith('📈')),
        len(lines),
    )
    prefix = lines[:insert]
    suffix = lines[insert:]
    if prefix and prefix[-1].strip():
        prefix.append('')
    prefix.extend(section.splitlines())
    if suffix:
        prefix.append('')
    return '\n'.join(prefix + suffix).strip()


def build_brief_card(today, decision_packet=None):
    """The WeChat card for the 盘前深度简报 — single source of truth shared by
    brief_postflight (primary send) and brief_watchdog (backstop).

    Preference order:
      1. LLM-written card at memory/.tmp/brief-card-{date}.txt — the rich TL;DR
         (核心结论 narrative) the model composes in the SKILL's Step 5.
      2. Deterministic fallback from memory/{date}-plan.json (book + ≤4 decisions +
         full-brief link) if the model didn't write the card file — never silent.

    In both paths the harness inserts/replaces the deterministic early-candidate
    section from the generation-bound packet. Model omission cannot hide it.
    """
    url = brief_url(today)
    decision_packet = decision_packet or _brief_decision_packet(today)
    card_file = WS / 'memory' / '.tmp' / f'brief-card-{today}.txt'
    try:
        if card_file.exists():
            txt = card_file.read_text().strip()
            if txt:
                return _inject_early_candidate_section(txt, decision_packet)
    except Exception:
        pass  # fall through to deterministic build
    lines = [f'📊 盘前深度简报｜{today} {BRIEF_SLOT_HKT} HKT']
    try:
        plan = json.loads((WS / 'memory' / f'{today}-plan.json').read_text())
        bk = plan.get('book') or {}
        if bk:
            try:
                bk = {**bk, **plan_totals(plan)}
            except ValueError:
                bk = {}
                lines.append('Book: 金额未核验，见完整报告')
        if bk:
            lines[0] += f' (USDHKD={plan["fx_rate_usdhkd"]})'
            lines.append(f"Book: USD${bk.get('usd_total_pnl', '?')} | "
                         f"HK leg {bk.get('hk_leg_hkd', '?')}HKD | US leg {bk.get('us_leg_usd', '?')}USD")
        acts = [a for a in (plan.get('decisions') or []) if isinstance(a, dict)][:4]
        if acts:
            lines.append('今日动作：')
            for i, a in enumerate(acts, 1):
                condition = a.get('condition') or {}
                trig = condition.get('price')
                trig = f"@{trig}" if trig is not None else (condition.get('type') or '')
                conf = a.get('confidence')
                try:
                    conf = f" conf{round(float(conf) * 100)}%" if conf is not None else ''
                except (TypeError, ValueError, OverflowError):
                    conf = ''
                lines.append(f"{i}. {a.get('ticker', '?')} [{a.get('strategy_id', '?')}] {a.get('action', '')} {trig}{conf}")
    except Exception:
        pass  # link-only fallback
    lines += ['', f'📈 完整报告：{url}']
    return _inject_early_candidate_section('\n'.join(lines), decision_packet)
