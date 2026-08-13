#!/usr/bin/env python3
"""
KCNyu influence radar — market-moving statements from high-impact figures.

Why: Trump / Musk statements move markets hours-to-days before they show up in
the per-ticker news digest. kcn wants two things surfaced:
  1. 撞持仓告警 — a figure names a company he holds → flag it loud
  2. 选股 idea  — a figure recommends/buys something he does NOT hold → watchlist

Sources:
  • Trump    — trumpstruth.org/feed   (RSS 2.0, FULL post text, ~mins fresh,
               primary source = his actual words, not second-hand coverage)
  • Musk     — Google News RSS proxy  (no reliable free X RSS in 2026; Nitter dead,
               xcancel needs per-reader email whitelist → unusable in GH Action.
               So we proxy via news coverage of his market-relevant statements.)
  • Serenity — aleabitoreddit.substack.com/feed  (AI/semi supply-chain "chokepoint"
               stock picker, huge on X. Her X firehose has no free RSS — same Musk
               dead-end, and paid X-scrapers need a funded account — so we take only
               her FREE public Substack posts. Low-frequency but primary-source.)

Pipeline:
  fetch → cheap keyword pre-filter (drop obvious noise) → ONE vendor LLM call
  that extracts {tickers, stance, relevance, held vs new-idea, CN summary} →
  split into held_hits / new_ideas → write assets/data/influencer_feed.json.

Merge-not-overwrite: if a source returns empty (rate-limit / outage) we keep the
previous run's items for that source so one bad fetch can't blank the card
(see memory/openclaw-fetcher-merge-not-overwrite.md).

Env: MINIMAX_API_KEY primary; XIAOMI_API_KEY optional fallback. Without either,
falls back to keyword-only items with relevance=null (still renders, just noisier).
"""
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from clawock.safe_io import safe_write_json
from clawock.market_data.sentiment import fetch_google_news
from clawock.workspace import workspace_root

WS_ROOT = str(workspace_root(Path.cwd()))
OUT_FILE = os.path.join(WS_ROOT, 'assets', 'data', 'influencer_feed.json')

UA = 'clawock-influencer-scan/1.0 (github.com/KCNyu/clawock)'
HEADERS = {'User-Agent': UA}
TIMEOUT = 12
LOOKBACK_HOURS = 48          # catch weekend posts before Mon brief
RELEVANCE_CUTOFF = 45        # LLM score below this dropped; low so radar stays full
MAX_CANDIDATES = 40          # cap sent to LLM (token guard)

# Cheap pre-filter: a raw post is a candidate only if it smells market/economy/
# policy-relevant. The LLM is the smart filter downstream — this gate is just a
# token cost-guard, so keep it BROAD (Trump's tariff/Fed/China/energy posts move
# markets even without finance vocab). Better to over-include here and let the
# LLM score relevance than to silently drop a market-moving post pre-LLM.
MARKET_KEYWORDS = [
    # markets / finance
    'stock', 'shares', 'market', 'nasdaq', 'dow', 's&p', 'invest', 'buy', 'sell',
    'bought', 'company', 'companies', 'ipo', 'earnings', 'profit', 'revenue',
    'short ', 'long ', 'recommend', 'great company', '$',
    # macro / policy (Trump's bread and butter — all market-moving)
    'tariff', 'tariffs', 'trade', 'trade deal', 'fed', 'powell', 'interest',
    'rate', 'rates', 'inflation', 'dollar', 'economy', 'economic', 'jobs',
    'tax', 'taxes', 'sanction', 'china', 'chip', 'chips', 'semiconductor',
    'energy', 'oil', 'gas', 'drill', 'gold', 'steel', 'manufactur', 'factory',
    'defense', 'pharma', 'drug', 'bank', 'antitrust', 'merger', 'acquisition',
    'deal', 'sec ', 'regulat',
    # crypto / themes
    'crypto', 'bitcoin', 'dogecoin', 'stablecoin', 'digital asset', 'ai ',
    # mega-cap / common names Trump or Musk name directly
    'tesla', 'spacex', 'xai', 'nvidia', 'apple', 'meta', 'google', 'amazon',
    'microsoft', 'intel', 'boeing', 'ev ', 'truth social', 'djt',
]


def _strip_html(s):
    """trumpstruth <description> carries HTML — flatten to plain text."""
    s = re.sub(r'<br\s*/?>', ' ', s or '', flags=re.I)
    s = re.sub(r'<[^>]+>', '', s)
    return html.unescape(s).strip()


def _is_candidate(text):
    t = (text or '').lower()
    return any(k in t for k in MARKET_KEYWORDS)


def _within_lookback(dt, cutoff):
    try:
        return dt is not None and dt >= cutoff
    except Exception:
        return True  # keep if we can't parse the date rather than drop


def _source_status(items):
    return 'success' if items else 'success_empty'


def _parse_published(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def fetch_trump(cutoff):
    """trumpstruth.org RSS — full post text. Returns (items, source status)."""
    out = []
    try:
        r = requests.get('https://trumpstruth.org/feed', headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f'  ⚠️ trump feed HTTP {r.status_code}', file=sys.stderr)
            return out, 'failed'
        root = ET.fromstring(r.text)
        for it in root.findall('.//item'):
            title = (it.findtext('title') or '').strip()
            desc = (it.findtext('description') or '').strip()
            link = (it.findtext('link') or '').strip()
            pub_raw = (it.findtext('pubDate') or '').strip()
            text = _strip_html(desc) or _strip_html(title)
            try:
                pub = parsedate_to_datetime(pub_raw) if pub_raw else None
                if pub and pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
            except Exception:
                pub = None
            if not _within_lookback(pub, cutoff):
                continue
            if not _is_candidate(text):
                continue
            out.append({
                'author':    'Trump',
                'text':      text[:600],
                'url':       link,
                'published': pub.isoformat() if pub else pub_raw,
                'origin':    'truthsocial',
            })
    except Exception as e:
        print(f'  ⚠️ trump feed: {e}', file=sys.stderr)
        return out, 'failed'
    return out, _source_status(out)


MUSK_MAX = 8  # second-hand source — cap so SpaceX-IPO rehash doesn't drown Trump


def fetch_musk():
    """Google News RSS proxy for Musk's market-relevant statements (second-hand).

    Google News returns the same hot story (e.g. SpaceX IPO) from a dozen outlets,
    so we dedup on a coarse headline signature and cap the count.
    """
    out, seen = [], set()
    query = 'Elon Musk (Tesla OR DOGE OR crypto OR stock OR buy OR SpaceX OR xAI)'
    news, fetch_status = fetch_google_news(
        query, hl='en-US', gl='US', limit=20, return_status=True)
    for it in news:
        title = it.get('title', '')
        if not _is_candidate(title) and 'musk' not in title.lower():
            continue
        # Coarse dedup: signature = sorted significant words (>4 chars, lowercased).
        sig = frozenset(w for w in re.findall(r'[a-z]{5,}', title.lower())
                        if w not in ('musk', 'could', 'about', 'after', 'their'))
        if any(len(sig & s) >= 3 for s in seen):  # ≥3 shared keywords → same story
            continue
        seen.add(sig)
        out.append({
            'author':    'Musk',
            'text':      title[:400],
            'url':       '',  # GNews wraps links; title carries the signal
            'published': it.get('published', ''),
            'origin':    'gnews-rss',
            'source':    it.get('source', ''),
        })
        if len(out) >= MUSK_MAX:
            break
    if fetch_status == 'failed':
        return out, 'failed'
    return out, _source_status(out)


# Serenity (@aleabitoreddit) — her X firehose has no free RSS (same Musk dead-end)
# and her depth is largely paywalled, so only her FREE public posts hit this feed →
# low-frequency (often nothing in a 48h window). That's correct for a radar: she
# surfaces only when she drops a fresh public idea. Pure-finance source, so unlike
# Trump we skip the market-keyword gate (every post is a candidate).
SERENITY_FEED = 'https://aleabitoreddit.substack.com/feed'
# DORMANT ON GHA BY DESIGN (confirmed 2026-06-07): Substack/Cloudflare IP-blocks the
# GitHub-Actions datacenter ranges → 403 regardless of UA (browser UA tested, still 403;
# free proxies allorigins/corsproxy/jina all failed too). Same wall as the X-RSS dead-end.
# So in the GHA influencer-scan this fetch returns [] and Serenity never appears — kcn
# accepted this (the serenity-skill methodology is the kept deliverable, not this feed).
# The code stays because it WORKS from a non-blocked IP (e.g. the local host returns 200),
# so it self-activates if ever run off-GHA. Browser UA + RSS Accept kept for that path.
# Don't re-debug the 403 — it's the IP, not the code.
SERENITY_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'),
    'Accept': 'application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}


def fetch_serenity(cutoff):
    """Serenity's Substack RSS — title + teaser (carries the thesis + cashtags).

    We use <description> (a compact teaser, e.g. "...among $LITE, $COHR, $MTSI...")
    not <content:encoded> (a 60KB+ full-text HTML body that would blow the LLM token
    budget). Returns [] on both fetch failure AND no-recent-post — and main() does
    NOT retain her prior items on an empty fetch, because empty is her normal state,
    not an outage (see the Trump/Musk retention note in main)."""
    out = []
    try:
        r = requests.get(SERENITY_FEED, headers=SERENITY_HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f'  ⚠️ serenity feed HTTP {r.status_code}', file=sys.stderr)
            return out, 'failed'
        root = ET.fromstring(r.text)
        for it in root.findall('.//item'):
            title = (it.findtext('title') or '').strip()
            desc = _strip_html(it.findtext('description') or '')
            link = (it.findtext('link') or '').strip()
            pub_raw = (it.findtext('pubDate') or '').strip()
            try:
                pub = parsedate_to_datetime(pub_raw) if pub_raw else None
                if pub and pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
            except Exception:
                pub = None
            if not _within_lookback(pub, cutoff):
                continue
            # Lead with the title (the thesis headline), then the teaser body.
            text = f'{title}. {desc}'.strip('. ') if title else desc
            if not text:
                continue
            out.append({
                'author':    'Serenity',
                'text':      text[:600],
                'url':       link,
                'published': pub.isoformat() if pub else pub_raw,
                'origin':    'substack',
            })
    except Exception as e:
        print(f'  ⚠️ serenity feed: {e}', file=sys.stderr)
        return out, 'failed'
    return out, _source_status(out)


def _dedup_sig(text):
    """Normalized signature for exact/near-exact dedup: drop a leading `RT @handle`,
    lowercase, keep only alnum + CJK. Trump's feed re-lists the same post (and
    retweets) verbatim, so identical text must collapse to one item."""
    t = re.sub(r'^\s*rt\s+@\w+', '', (text or '').lower().strip())
    return re.sub(r'[^a-z0-9一-鿿]+', '', t)[:120]


def dedup_items(items):
    """Collapse items sharing a normalized text signature, keeping the first."""
    seen, out = set(), []
    for it in items:
        sig = _dedup_sig(it.get('text', ''))
        if sig and sig in seen:
            continue
        seen.add(sig)
        out.append(it)
    return out


def load_holdings():
    """Held tickers + names (+ leveraged-ETF underlying hint) for LLM matching."""
    p = json.load(open(os.path.join(WS_ROOT, 'portfolio.json'), encoding='utf-8'))
    held = []
    for region in ('us_stocks', 'hk_stocks'):
        for h in p['portfolios'].get(region, {}).get('holdings', []):
            if h.get('shares', 0) > 0:
                held.append({
                    'ticker': h['ticker'],
                    'name':   h.get('name', ''),
                    'region': 'US' if region == 'us_stocks' else 'HK',
                })
    return held


LLM_SYSTEM = (
    "你是 kcn 的市场情报分析师。给你一批 Trump / Musk / Serenity 的言论(或对其言论的新闻报道)，"
    "以及 kcn 当前的持仓清单。其中 Serenity(@aleabitoreddit)是 AI/半导体供应链'卡点'选股博主，"
    "她直接点名的多是小众半导体/光通信标的(常带 $cashtag)，几乎都属于'选股 idea'(new_ideas)。"
    "任务：挑出有市场含义的条目，提取结构化信息。\n"
    "判定要点：\n"
    "- **倾向多列、宁滥勿缺**：这是一个'雷达'，凡涉及具体公司/股票/资产，或买卖/看多看空/"
    "背书/抨击，或宏观政策(关税/Fed/利率/中国/能源/税/监管/加密等会动板块的)，都列出来，"
    "用 relevance 分数反映强度(强信号 75-95，宏观/间接 50-70)，让前端按分排序。\n"
    "- **只有纯人身攻击/纯选举口水/与任何经济或市场都无关**的，才不返回(或给 <45)。\n"
    "- 同一事件被多条新闻重复报道时，只保留信息量最高的一条，别灌水。\n"
    "- tickers 只填言论**直接点名或直接讲的**上市标的。严禁'同板块/可能利好行业/"
    "竞争对手'这类联想式硬塞——SpaceX 的新闻不要因为 Rocket Lab 也是航天股就填 RKLB。\n"
    "- SpaceX / xAI / OpenAI 等**未上市**公司不计入 tickers(没有可交易代码)。\n"
    "- 杠杆 ETF 视作对应正股(PLTU=PLTR, ROBN=HOOD, MSFU=MSFT 等)做持仓匹配。\n"
    "- held = 言论直接点名、且命中 kcn 持仓的 ticker；new_ideas = 直接点名但 kcn "
    "**没持有**的 ticker(选股线索)。两者都基于'直接点名'，不基于板块联想。\n"
    "- stance ∈ {endorse(看多/推荐), buy, attack(抨击/看空), sell, neutral}。\n"
    "- sectors = 言论涉及的板块/主题(中文，如 加密货币/AI/航天/电动车/半导体/关税)，"
    "即使没点名具体公司也填。\n"
    "- sector_holdings = kcn 持仓清单里、业务属于上述 sectors 的 ticker(你了解这些公司业务)。"
    "用于把宏观主题软关联到他的持仓——例如挺加密→他的 CRCL。这是'板块相关'不是'直接点名'。\n"
    "- summary_cn = 一句话中文，点出 谁-对什么标的或板块-什么态度。\n"
    "只返回 JSON，格式：{\"items\":[{\"idx\":int, \"tickers\":[...], \"held\":[...], "
    "\"new_ideas\":[...], \"sectors\":[...], \"sector_holdings\":[...], \"stance\":\"...\", "
    "\"relevance\":0-100, \"summary_cn\":\"...\"}]}。idx 对应输入条目编号。不相关的条目可不返回。"
)


def llm_filter(candidates, held):
    """Returns dict {idx: {tickers, held, new_ideas, stance, relevance, summary_cn}}."""
    if not candidates:
        return {}
    if not (os.environ.get('MINIMAX_API_KEY') or os.environ.get('XIAOMI_API_KEY')):
        print('  ⚠️ no LLM provider key — skipping relevance filter (keyword-only)', file=sys.stderr)
        return {}
    from clawock.automation.llm import chat
    held_lines = '\n'.join(f"  - {h['ticker']} ({h['name']}, {h['region']})" for h in held)
    cand_lines = '\n'.join(
        f"[{i}] ({c['author']}) {c['text']}" for i, c in enumerate(candidates)
    )
    user = (
        f"kcn 持仓清单：\n{held_lines}\n\n"
        f"待筛选言论(共 {len(candidates)} 条)：\n{cand_lines}"
    )
    # Structured extraction — disable thinking (deterministic, avoids the
    # reasoning budget eating the output cap → truncated JSON) and give
    # headroom for ~40 items of JSON. mimo intermittently bails on a large
    # batch (returns an empty `{"items":[]}`, ~6 output tokens) — likely CN
    # endpoint moderation choking on Trump's political posts. An empty result
    # parses fine so it never raised; we now treat "empty despite candidates"
    # as a failure and retry, so the feed isn't silently dumped as raw English.
    for attempt in (1, 2):
        try:
            raw = chat(system=LLM_SYSTEM, user=user, max_tokens=8000,
                       temperature=0.3, json_response=True, thinking_disabled=True)
            data = json.loads(raw)
            scored = {int(it['idx']): it for it in data.get('items', []) if 'idx' in it}
            if scored:
                return scored
            print(f'  ⚠️ LLM returned 0 scored items for {len(candidates)} candidates '
                  f'(attempt {attempt}/2)', file=sys.stderr)
        except Exception as e:
            print(f'  ⚠️ LLM filter failed (attempt {attempt}/2): {e}', file=sys.stderr)
    return {}


def main():
    generated = datetime.now(timezone.utc)
    cutoff = generated - timedelta(hours=LOOKBACK_HOURS)

    trump, trump_status = fetch_trump(cutoff)
    musk, musk_status = fetch_musk()
    serenity, serenity_status = fetch_serenity(cutoff)
    source_status = {
        'trump': trump_status,
        'musk': musk_status,
        'serenity': serenity_status,
    }
    print(f'  raw: trump={len(trump)} musk={len(musk)} serenity={len(serenity)} '
          f'(after keyword pre-filter)')

    # Load previous run for merge-not-overwrite per source.
    prev = {}
    if os.path.exists(OUT_FILE):
        try:
            prev = json.load(open(OUT_FILE, encoding='utf-8'))
        except Exception:
            prev = {}
    prev_items = prev.get('items', [])

    candidates = dedup_items(trump + musk + serenity)[:MAX_CANDIDATES]
    held = load_holdings()
    held_tickers = {h['ticker'] for h in held}
    scored = llm_filter(candidates, held)

    items = []
    for i, c in enumerate(candidates):
        s = scored.get(i)
        if s is None:
            # No LLM verdict: keep only if LLM was unavailable entirely (keyword mode).
            if scored:
                continue  # LLM ran but judged this not relevant → drop
            c.update({'tickers': [], 'held': [], 'new_ideas': [],
                      'stance': 'neutral', 'relevance': None, 'summary_cn': ''})
            items.append(c)
            continue
        if (s.get('relevance') or 0) < RELEVANCE_CUTOFF:
            continue
        # Trust code, not LLM, for the held/new split (LLM proposes tickers, we verify).
        tickers = [t.strip().upper() for t in s.get('tickers', []) if t]
        held_hit = sorted({t for t in tickers if t in held_tickers}
                          | {t.strip().upper() for t in s.get('held', [])
                             if t.strip().upper() in held_tickers})
        new_ideas = sorted({t for t in tickers if t not in held_tickers})
        # Soft sector link: holdings the LLM says fall in the mentioned sector,
        # minus any already counted as a direct held hit (don't double-flag).
        sector_holdings = sorted({t.strip().upper() for t in s.get('sector_holdings', [])
                                  if t.strip().upper() in held_tickers} - set(held_hit))
        c.update({
            'tickers':    tickers,
            'held':       held_hit,
            'new_ideas':  new_ideas,
            'sectors':    [str(x).strip() for x in s.get('sectors', []) if x],
            'sector_holdings': sector_holdings,
            'stance':     s.get('stance', 'neutral'),
            'relevance':  s.get('relevance'),
            'summary_cn': s.get('summary_cn', ''),
        })
        items.append(c)

    # Merge-not-overwrite: only when the raw FETCH failed (network/outage) do we
    # retain a source's prior items. A source legitimately producing zero items
    # because the LLM judged everything irrelevant is NOT an outage — don't
    # resurrect stale (possibly unfiltered) posts in that case.
    # Serenity is deliberately NOT retained here: she posts publicly so rarely that
    # an empty fetch is her normal state, not an outage — retaining would pin a
    # weeks-old idea on the radar forever. She simply drops off until she posts again.
    author_sources = {'Trump': 'trump', 'Musk': 'musk'}
    for author, source in author_sources.items():
        if source_status[source] == 'failed':
            retained = []
            for prior in prev_items:
                if prior.get('author') != author:
                    continue
                published = _parse_published(prior.get('published'))
                if published is None or published < cutoff:
                    continue
                item = dict(prior)
                item['retained_from_previous'] = True
                retained.append(item)
            if retained:
                print(f'  ↻ {author} fetch failed — retaining {len(retained)} prior items',
                      file=sys.stderr)
                items.extend(retained)

    # Final guard: prior-item merge can re-introduce a post already in this run.
    items = dedup_items(items)

    # Rank by signal value, not recency: held-hit > new-idea > sector > general,
    # then by relevance, then recency. Keeps the valuable stuff on top instead of
    # letting repetitive second-hand Musk headlines (recent) dominate the feed.
    def _rank(x):
        tier = 3 if x.get('held') else (2 if x.get('new_ideas')
               else (1 if x.get('sector_holdings') else 0))
        return (tier, x.get('relevance') or 0, x.get('published') or '')
    items.sort(key=_rank, reverse=True)

    held_hits = [it for it in items if it.get('held')]
    new_ideas = [it for it in items if it.get('new_ideas') and not it.get('held')]
    # Sector-related: thematic link to a holding, but no direct name → softer tier.
    sector_hits = [it for it in items
                   if it.get('sector_holdings') and not it.get('held') and not it.get('new_ideas')]

    out = {
        'generated_at':  generated.isoformat(),
        'lookback_hours': LOOKBACK_HOURS,
        'sources': {
            'trump':    'trumpstruth.org/feed (primary)',
            'musk':     'google-news-rss (proxy)',
            'serenity': 'aleabitoreddit.substack.com/feed (public posts)',
        },
        'source_status': source_status,
        'llm_filtered':  bool(scored),
        'counts': {
            'total':       len(items),
            'held_hits':   len(held_hits),
            'new_ideas':   len(new_ideas),
            'sector_hits': len(sector_hits),
        },
        'items':       items[:30],
        'held_hits':   held_hits[:10],
        'new_ideas':   new_ideas[:10],
        'sector_hits': sector_hits[:10],
    }
    safe_write_json(OUT_FILE, out)
    print(f'✓ wrote {OUT_FILE}: {len(items)} items '
          f'({len(held_hits)} held-hits, {len(new_ideas)} new-ideas, '
          f'{len(sector_hits)} sector-hits)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
