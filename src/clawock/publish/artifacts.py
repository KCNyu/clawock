#!/usr/bin/env python3
"""Behavioral validation for workflow-generated publication artifacts.

Run as ``clawock validate-sidecar <name>``.
"""
from __future__ import annotations

import csv
import argparse
import json
import math
import os
import re
import struct
import sys
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


from clawock.workspace import workspace_root

ROOT = workspace_root(Path.cwd())
DASHBOARD_MAX_BYTES = 200_000
OVERVIEW_MAX_BYTES = 80_000
DASHBOARD_MONEY_INTEGRITY_CODES = frozenset({
    'VALUE_LEG', 'TCV_SUM', 'COST_TOTAL', 'PNL_TOTAL', 'PNL_PCT',
    'PNL_LEG', 'TODAY_LEG', 'TODAY_TOTAL', 'CASH_RECON', 'CASH_SANITY',
    'REALIZED_SUM', 'COST_BASIS', 'FX_TAG', 'TRUE_PRINCIPAL', 'GOLD_RECON',
})


def validate_macro(path: Path | str, *, now: datetime | None = None) -> None:
    path = Path(path)
    assert path.is_file(), f'macro snapshot missing: {path}'
    try:
        raw = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise AssertionError('file is not valid UTF-8') from None
    assert raw.strip(), 'file is empty'
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f'invalid JSON at line {exc.lineno} column {exc.colno}') from None
    assert isinstance(data, dict), 'top-level JSON must be an object'

    generated_at = data.get('generated_at')
    assert isinstance(generated_at, str), 'generated_at missing'
    try:
        generated = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    except ValueError:
        raise AssertionError('generated_at is not a valid ISO timestamp') from None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age = current.astimezone(timezone.utc) - generated.astimezone(timezone.utc)
    freshness_limit = timedelta(hours=18)
    assert age <= freshness_limit, (
        f'generated_at is stale: age {age.total_seconds() / 3600:.2f}h exceeds 18h')

    def finite_number(value):
        return (isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value))

    quote_fields = ('vix', 'treasury_10y', 'dxy', 'hsi', 'hstech', 'spx', 'nasdaq')
    quote_sources = ('stooq', 'tencent', 'yahoo')
    market_quotes = [
        field for field in quote_fields
        if isinstance(data.get(field), dict)
        and finite_number(data[field].get('price'))
        and data[field]['price'] > 0
        and data[field].get('source') in quote_sources
    ]
    supplemental = []
    fear_greed = data.get('fear_greed')
    if isinstance(fear_greed, dict) and finite_number(fear_greed.get('score')):
        supplemental.append('fear_greed')
    fed_press = data.get('fed_press')
    if (isinstance(fed_press, list)
            and any(isinstance(item, dict) and str(item.get('title', '')).strip()
                    for item in fed_press)):
        supplemental.append('fed_press')

    assert market_quotes, 'snapshot has zero successful market quotes'
    successful = market_quotes + supplemental
    print(f'macro coverage validation OK: {", ".join(successful)}; '
          f'age={age.total_seconds() / 3600:.2f}h')


def validate_sentiment(
        path: Path | str, portfolio_path: Path | str = 'portfolio.json') -> None:
    path = Path(path)
    portfolio_path = Path(portfolio_path)
    assert path.is_file(), f'sentiment snapshot missing: {path}'
    try:
        raw = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise AssertionError('file is not valid UTF-8') from None
    assert raw.strip(), 'file is empty'
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f'invalid JSON at line {exc.lineno} column {exc.colno}') from None
    assert isinstance(data, dict), 'top-level JSON must be an object'

    generated_at = data.get('generated_at')
    assert isinstance(generated_at, str), 'generated_at missing'
    try:
        datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    except ValueError:
        raise AssertionError('generated_at is not a valid ISO timestamp') from None
    sources = data.get('sources')
    assert isinstance(sources, list) and sources, 'sources missing or empty'
    assert all(isinstance(source, str) and source.strip() for source in sources), (
        'sources must contain non-empty strings')

    assert portfolio_path.is_file(), f'portfolio missing: {portfolio_path}'
    portfolio = json.loads(portfolio_path.read_text(encoding='utf-8'))
    expected = {
        holding['ticker']
        for region in ('us_stocks', 'hk_stocks')
        for holding in portfolio['portfolios'].get(region, {}).get('holdings', [])
        if holding.get('shares', 0) > 0
    }

    tickers = data.get('tickers')
    assert isinstance(tickers, list), 'tickers must be a list'
    scanned = set()
    result_count = 0
    for index, row in enumerate(tickers):
        assert isinstance(row, dict), f'ticker result {index} is not an object'
        ticker = row.get('ticker')
        assert isinstance(ticker, str) and ticker.strip(), (
            f'ticker result {index} missing ticker')
        assert isinstance(row.get('name'), str), f'{ticker} name must be a string'
        assert row.get('region') in ('us_stocks', 'hk_stocks'), (
            f'{ticker} has invalid region')
        mentions = row.get('reddit_mentions_7d')
        assert (isinstance(mentions, int) and not isinstance(mentions, bool)
                and mentions >= 0), f'{ticker} has invalid reddit mention count'
        result_count += mentions
        result_fields = ('reddit_posts', 'google_news_en', 'google_news_zh')
        for field in result_fields:
            results = row.get(field)
            assert isinstance(results, list), f'{ticker} {field} must be a list'
            assert all(isinstance(item, dict) for item in results), (
                f'{ticker} {field} contains a malformed item')
            result_count += len(results)
        scanned.add(ticker)

    missing = sorted(expected - scanned)
    assert not missing, f'sentiment snapshot missing active tickers: {", ".join(missing)}'
    source_status = data.get('source_status')
    if scanned and result_count == 0 and source_status is not None:
        healthy = (isinstance(source_status, dict)
                   and any(status == 'ok' for status in source_status.values()))
        assert healthy, 'sentiment: all sources failed'
    print(f'sentiment structural validation OK: {len(scanned)} tickers (zero results allowed)')


def validate_influencer(path: Path | str) -> None:
    path = Path(path)
    assert path.is_file(), f'influencer feed missing: {path}'
    try:
        raw = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise AssertionError('file is not valid UTF-8') from None
    assert raw.strip(), 'file is empty'
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f'invalid JSON at line {exc.lineno} column {exc.colno}') from None
    assert isinstance(data, dict), 'top-level JSON must be an object'

    generated_at = data.get('generated_at')
    assert isinstance(generated_at, str), 'generated_at missing'
    try:
        generated = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    except ValueError:
        raise AssertionError('generated_at is not a valid ISO timestamp') from None
    generated = generated.replace(tzinfo=generated.tzinfo or timezone.utc)

    items = data.get('items')
    assert isinstance(items, list), 'items must be a list'
    for index, item in enumerate(items):
        assert isinstance(item, dict), f'item {index} is not an object'
        author = item.get('author')
        assert isinstance(author, str) and author.strip(), f'item {index} missing author'
        text = item.get('text')
        assert isinstance(text, str) and text.strip(), f'item {index} missing text'
        relevance = item.get('relevance')
        assert (relevance is None
                or (isinstance(relevance, (int, float))
                    and not isinstance(relevance, bool)
                    and math.isfinite(relevance))), (
            f'item {index} has invalid relevance')
        if item.get('retained_from_previous'):
            lookback_hours = data.get('lookback_hours')
            assert (isinstance(lookback_hours, (int, float))
                    and not isinstance(lookback_hours, bool)
                    and math.isfinite(lookback_hours)
                    and lookback_hours > 0), 'lookback_hours missing or invalid'
            published = item.get('published')
            assert isinstance(published, str) and published.strip(), (
                f'retained item {index} missing published timestamp')
            try:
                try:
                    published_at = datetime.fromisoformat(
                        published.replace('Z', '+00:00'))
                except ValueError:
                    published_at = parsedate_to_datetime(published)
            except (TypeError, ValueError):
                raise AssertionError(
                    f'retained item {index} has invalid published timestamp') from None
            published_at = published_at.replace(
                tzinfo=published_at.tzinfo or timezone.utc)
            age = generated.astimezone(timezone.utc) - published_at.astimezone(timezone.utc)
            assert age <= timedelta(hours=lookback_hours), (
                f'retained item {index} exceeds declared lookback window')

    sources = data.get('sources')
    assert isinstance(sources, dict) and sources, 'sources missing or empty'
    assert all(isinstance(name, str) and name.strip()
               and isinstance(source, str) and source.strip()
               for name, source in sources.items()), (
        'sources must map non-empty names to non-empty descriptions')
    source_status = data.get('source_status')
    if source_status is not None:
        allowed_statuses = {'success', 'success_empty', 'failed'}
        assert isinstance(source_status, dict) and source_status, (
            'source_status must be a non-empty object')
        assert all(status in allowed_statuses for status in source_status.values()), (
            'source_status contains an invalid status')
        if not items:
            assert any(status != 'failed' for status in source_status.values()), (
                'influencer: all sources failed')

    counts = data.get('counts')
    assert isinstance(counts, dict), 'counts missing'
    summary_lists = ('held_hits', 'new_ideas', 'sector_hits')
    for field in summary_lists:
        assert isinstance(data.get(field), list), f'{field} must be a list'
        assert all(isinstance(item, dict) for item in data[field]), (
            f'{field} contains a malformed item')
        count = counts.get(field)
        assert isinstance(count, int) and count >= len(data[field]), (
            f'{field} count/list mismatch')
    total = counts.get('total')
    assert isinstance(total, int) and total >= len(items), (
        'total count/items mismatch')
    print(f'influencer structural validation OK: {len(items)} items (empty allowed)')


def validate_news_digest(
        path: Path | str, *, now: datetime | None = None) -> None:
    path = Path(path)
    assert path.is_file(), f'news digest missing: {path}'
    try:
        raw = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise AssertionError('file is not valid UTF-8') from None
    assert raw.strip(), 'file is empty'
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f'invalid JSON at line {exc.lineno} column {exc.colno}') from None
    assert isinstance(data, dict), 'top-level JSON must be an object'

    generated_at = data.get('generated_at')
    assert isinstance(generated_at, str), 'generated_at missing'
    try:
        generated = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    except ValueError:
        raise AssertionError('generated_at is not a valid ISO timestamp') from None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age = current.astimezone(timezone.utc) - generated.astimezone(timezone.utc)
    freshness_limit = timedelta(hours=18)
    assert age <= freshness_limit, (
        f'generated_at is stale: age {age.total_seconds() / 3600:.2f}h exceeds 18h')

    tickers = data.get('tickers')
    counts = data.get('raw_news_counts')
    digest = data.get('digest_markdown')
    assert isinstance(tickers, list), 'tickers must be a list'
    assert isinstance(counts, dict), 'raw_news_counts must be an object'
    invalid_counts = [key for key, value in counts.items()
                      if not isinstance(value, int) or isinstance(value, bool)]
    assert not invalid_counts, (
        f'raw_news_counts values must be integers: {invalid_counts}')
    evidence = data.get('raw_news_evidence')
    if evidence is not None:
        assert isinstance(evidence, dict), (
            'raw_news_evidence must be an object'
        )
        assert set(evidence) == set(counts), (
            'raw_news_evidence ticker coverage must match raw_news_counts'
        )
        allowed = {'headline', 'datetime', 'source', 'origin', 'url'}
        forbidden = {'summary', 'body', 'content', 'description'}
        for ticker, items in evidence.items():
            assert isinstance(items, list), (
                f'raw_news_evidence[{ticker}] must be a list'
            )
            assert len(items) == counts[ticker], (
                f'raw_news_evidence[{ticker}] count mismatch'
            )
            for index, item in enumerate(items):
                assert isinstance(item, dict), (
                    f'raw_news_evidence[{ticker}][{index}] must be an object'
                )
                assert not (set(item) & forbidden), (
                    'raw_news_evidence must not persist article summaries/bodies'
                )
                assert set(item) <= allowed, (
                    f'raw_news_evidence[{ticker}][{index}] has unknown fields'
                )
                assert str(item.get('headline') or '').strip(), (
                    f'raw_news_evidence[{ticker}][{index}] headline missing'
                )
    total_news = sum(counts.values())
    if data.get('no_material_news') is True:
        assert total_news == 0, 'no_material_news digest contains source news'
        assert isinstance(digest, str) and not digest.strip(), (
            'no_material_news digest must not fabricate a narrative')
        if tickers:
            source_status = data.get('source_status')
            assert isinstance(source_status, dict), (
                'no_material_news source_status must be an object')
            statuses = [
                status
                for per_ticker in source_status.values()
                if isinstance(per_ticker, dict)
                for status in per_ticker.values()
            ]
            assert 'success_empty' in statuses, (
                'no_material_news has no successful empty source')
        print(f'digest validation OK: explicit no-material-news artifact; '
              f'age={age.total_seconds() / 3600:.2f}h')
        return

    assert tickers, 'tickers missing or empty'
    assert total_news > 0, 'no source news in generated digest'
    assert isinstance(digest, str) and len(digest.strip()) >= 100, (
        'LLM digest empty or implausibly short')
    # Structure proxy: a real digest is markdown headers + bullets, not a prose
    # wall / refusal / JSON echo. Accept h2 OR h3 (`## ` / `### `) — pinning the
    # literal `### ` broke the digest for 3 days from 2026-07-21 when MiniMax M3
    # started emitting `## ` section headers with otherwise perfect content. The
    # header level is cosmetic (build_dashboard renders the markdown either way);
    # what the gate must catch is "no structure at all", so also require a bullet.
    assert re.search(r'(?m)^#{2,3} ', digest), (
        'LLM digest has no h2/h3 markdown header (## or ###)')
    assert re.search(r'(?m)^\s*[-*] ', digest), (
        'LLM digest has no bullet points')
    print(f'digest validation OK: {len(digest)} chars, {total_news} source items; '
          f'age={age.total_seconds() / 3600:.2f}h')


def validate_eod_archive(
        csv_path: Path | str,
        portfolio_path: Path | str,
        *,
        snapshot_date: str | None = None,
) -> None:
    portfolio_path = Path(portfolio_path)
    snapshot_date = snapshot_date or str(date.today())
    expected = None
    held = []
    if portfolio_path.is_file():
        portfolio = json.loads(portfolio_path.read_text(encoding='utf-8'))
        held = [
            holding
            for region in ('us_stocks', 'hk_stocks')
            for holding in portfolio['portfolios'].get(region, {}).get('holdings', [])
            if holding.get('shares', 0) > 0
        ]
        expected = {h['ticker'] for h in held}
        if not expected:
            print(f'EOD archive coverage validation OK: all-cash portfolio, 0 rows for {snapshot_date}')
            return

    path = Path(csv_path)
    assert path.is_file(), f'EOD archive missing: {path}'
    expected_fields = (
        'date', 'ticker', 'name', 'currency', 'shares', 'cost_basis',
        'current_price', 'pnl_pct', 'current_value',
    )
    try:
        with path.open(newline='', encoding='utf-8') as handle:
            reader = csv.DictReader(handle)
            assert tuple(reader.fieldnames or ()) == expected_fields, (
                f'EOD archive schema mismatch: {reader.fieldnames}')
            rows = list(reader)
    except UnicodeDecodeError:
        raise AssertionError('file is not valid UTF-8') from None

    today_rows = [row for row in rows if row['date'] == snapshot_date]
    for index, row in enumerate(today_rows, start=1):
        ticker = row.get('ticker')
        if not isinstance(ticker, str) or not ticker.strip():
            print(
                f'ASSERTION FAILED: EOD archive {path}: malformed row {index} '
                f'for {snapshot_date}: ticker missing',
                file=sys.stderr,
            )
            raise SystemExit(1)
    assert expected is not None, f'portfolio missing: {portfolio_path}'
    today_tickers = {row['ticker'] for row in today_rows}
    missing = sorted(expected - today_tickers)
    assert not missing, (
        f'EOD archive missing active tickers for {snapshot_date}: {", ".join(missing)}')
    keys = [(row['ticker'], row['currency']) for row in today_rows]
    assert len(keys) == len(set(keys)), f'duplicate EOD rows for {snapshot_date}'

    def finite_number(value):
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    for row in today_rows:
        assert row['currency'] in ('USD', 'HKD'), (
            f"unexpected EOD currency for {row['ticker']}: {row['currency']}")
        for field in ('shares', 'cost_basis', 'current_price', 'current_value'):
            assert finite_number(row[field]) and float(row[field]) > 0, (
                f"invalid EOD {field} for {row['ticker']}: {row[field]!r}")
        assert finite_number(row['pnl_pct']), (
            f"invalid EOD pnl_pct for {row['ticker']}: {row['pnl_pct']!r}")

    # Price freshness: the archive copies portfolio.json's current_price with no
    # refresh, so a held holding whose price hasn't updated (a broken quote fetch)
    # gets archived as this week's close (2026-07 audit finding #9). Each holding's
    # data_source embeds the quote date; a held holding priced more than
    # PRICE_STALE_DAYS before the snapshot is rejected. Fail-safe: a data_source
    # whose date can't be parsed is skipped (never a false archive failure), and
    # the window is generous enough to clear a long holiday weekend.
    PRICE_STALE_DAYS = 5
    snap = date.fromisoformat(snapshot_date)
    stale = []
    for h in held:
        qd = _quote_date(h.get('data_source', ''), snap)
        if qd is not None and (snap - qd).days > PRICE_STALE_DAYS:
            stale.append(f"{h['ticker']} ({(snap - qd).days}d old: {h.get('data_source','')[:48]!r})")
    assert not stale, (
        f'EOD archive price is stale for {snapshot_date} — quote not refreshed for: '
        + '; '.join(stale))
    print(f'EOD archive coverage validation OK: {len(today_rows)} rows for {snapshot_date}')


_MONTHS = {m: i for i, m in enumerate(
    ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), start=1)}


def _quote_date(data_source, ref):
    """Best-effort quote date from a free-text data_source, or None if unparseable.

    Handles the two live shapes — `... Jul 23, 2026 20:01 ET` and `Tencent Jul 24
    16:00 HKT` (no year) — plus `YYYY/MM/DD` / `YYYY-MM-DD`. A missing year is
    resolved to the most recent `Mon Day` at or before `ref` (so a Jan quote read
    on a late-Dec snapshot doesn't jump a year forward). None on any failure —
    callers must treat unparseable as 'skip', never 'stale'."""
    if not data_source:
        return None
    iso = re.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', data_source)
    if iso:
        try:
            return date(int(iso[1]), int(iso[2]), int(iso[3]))
        except ValueError:
            return None
    m = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})'
                  r'(?:,\s*(\d{4}))?', data_source)
    if not m:
        return None
    mon, day = _MONTHS[m[1]], int(m[2])
    try:
        if m[3]:
            return date(int(m[3]), mon, day)
        cand = date(ref.year, mon, day)
        return cand if cand <= ref else date(ref.year - 1, mon, day)
    except ValueError:
        return None


def validate_weekly_review(
        md_path: Path | str, *, week_id: str | None = None) -> None:
    path = Path(md_path)
    week_id = week_id or path.stem
    assert path.is_file(), f'weekly review missing: {path}'

    try:
        raw = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise AssertionError('file is not valid UTF-8') from None
    assert raw.startswith('---\n'), 'weekly review front matter missing'
    parts = raw.split('---', 2)
    assert len(parts) == 3, 'weekly review front matter is malformed'
    front_matter, body = parts[1], parts[2].strip()
    metadata = {}
    for line in front_matter.strip().splitlines():
        key, separator, value = line.partition(':')
        assert separator, f'malformed front matter line: {line!r}'
        metadata[key.strip()] = value.strip()

    assert metadata.get('layout') == 'default', 'unexpected weekly review layout'
    assert metadata.get('title') == f'周复盘 · {week_id}', 'weekly review title/week mismatch'
    assert len(body) >= 1000, f'weekly review implausibly short: {len(body)} chars'
    # Four required sections, each proven by a distinct SECTION MARKER (a markdown
    # heading `## …` OR a bold label `**…**` — the prompt asks for bold, MiniMax
    # drifts to headings). Matching an alias anywhere in the body would let a
    # counterfeit with four inline bold mentions pass; matching a distinct marker
    # line ties each concept to a real section. Aliases are ZH/EN because the model
    # drifts language (the committed 2026-W24.md uses English headers); ASCII
    # aliases are word-bounded so 'nav' matches "NAV" but not "navigation".
    # Each concept is a set of regex patterns matched against a marker line
    # (IGNORECASE). Patterns are FULL section phrases, not bare fragments: a bare
    # 风险/净值/校准/下周 matched unrelated headings like `## 风险提示` or
    # `## 净值口径说明` (2026-07 re-review). CJK phrases are literal; English uses
    # `\b…\b` word boundaries so 'nav' ≠ 'navigation'. `下周…关注` allows an inline
    # date range (`下周 (07/20-07/24) 关注`).
    # English aliases are CONTEXTUAL phrases, not bare words: bare nav/calibration/
    # next week/risk trend let a fully-English counterfeit pass (`NAV Methodology /
    # Model Calibration Method / Risk Trend Definitions / Next Week Calendar`,
    # 2026-07 re-review). Calibration requires plan/decision context so
    # `Plan Adherence & Calibration` passes but `Model Calibration Method` does not.
    section_patterns = {
        'NAV/净值':   (r'本周净值', r'周净值', r'\bweekly nav\b'),
        '决策/校准':  (r'决策兑现', r'决策校准',
                      r'\b(?:plan|decisions?)\b.{0,24}\b(?:adherence|calibration|brier)\b'),
        '风险演变':   (r'风险演变', r'\brisk evolution\b'),
        '下周关注':   (r'下周.{0,15}关注', r"\bnext week'?s? focus\b"),
    }

    markers = [ln.strip() for ln in body.splitlines()
               if re.match(r'^\s{0,3}#{1,6} \S', ln) or re.match(r'^\s{0,3}\*\*\S', ln)]
    matched = {}  # concept -> index of the marker line that satisfied it (distinct)
    for concept, patterns in section_patterns.items():
        for i, m in enumerate(markers):
            if i in matched.values():
                continue  # one marker line can't cover two concepts
            if any(re.search(p, m, re.IGNORECASE) for p in patterns):
                matched[concept] = i
                break
    missing = [c for c in section_patterns if c not in matched]
    assert not missing, (
        f'weekly review missing required section marker(s): {missing}; '
        f'section markers found: {markers[:12]}')
    print(f'weekly review validation OK: {path} ({len(body)} chars, '
          f'{len(markers)} section markers)')


DEFAULT_SCREENSHOTS = (
    ('site/assets/shadow-backtest.png', 20_000, 400, 200),
    ('site/assets/social-card.png', 150_000, 1_000, 500),
)


def validate_screenshots(
        screenshots: tuple[tuple[Path | str, int, int, int], ...] = DEFAULT_SCREENSHOTS,
) -> None:
    PNG_MAGIC = b'\x89PNG\r\n\x1a\n'

    for filename, min_size, min_width, min_height in screenshots:
        path = Path(filename)
        assert path.is_file(), f'missing screenshot: {filename}'
        size = path.stat().st_size
        assert size >= min_size, (
            f'screenshot too small: {filename} is {size} bytes; expected >= {min_size}'
        )
        header = path.read_bytes()[:24]
        assert header[:8] == PNG_MAGIC, f'invalid PNG magic: {filename}'
        assert header[12:16] == b'IHDR', f'missing PNG IHDR: {filename}'
        # Fully decode, not just parse the header: a valid PNG header + IHDR
        # dimensions on top of zero/garbage chunks passes the byte checks but is
        # an unopenable image (2026-07 audit). Pillow verify() walks every chunk.
        width, height = _decoded_png_size(path, filename)
        assert width >= min_width and height >= min_height, (
            f'implausible screenshot dimensions: {filename} is {width}x{height}; '
            f'expected >= {min_width}x{min_height}'
        )
        print(f'validated {filename}: {size} bytes, {width}x{height}')


def _decoded_png_size(path, label):
    """(width, height) from a FULLY-decoded PNG, or AssertionError. verify()
    consumes the file object, so re-open for the size read."""
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            assert im.format == 'PNG', f'{label}: not a PNG after decode ({im.format})'
            return im.size
    except (UnidentifiedImageError, OSError, SyntaxError, EOFError) as e:
        raise AssertionError(f'{label}: PNG does not decode ({type(e).__name__}: {e})') from None


def validate_gif(path: Path | str = 'site/assets/dashboard.gif') -> None:
    GIF_MAGICS = (b'GIF89a', b'GIF87a')
    MIN_GIF_SIZE = 300_000
    path = Path(path)

    assert path.is_file(), f'missing GIF: {path}'
    size = path.stat().st_size
    assert size >= MIN_GIF_SIZE, (
        f'GIF too small: {path} is {size} bytes; expected >= {MIN_GIF_SIZE}'
    )
    with path.open('rb') as gif:
        header = gif.read(10)
    assert header[:6] in GIF_MAGICS, f'invalid GIF magic: {path}'
    # Decode for real + count frames: a valid GIF header on padding passes the
    # magic/dimension byte checks but has no decodable frames (2026-07 audit). The
    # dashboard GIF is an animation, so require at least 2 frames.
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as im:
            assert im.format == 'GIF', f'{path}: not a GIF after decode ({im.format})'
            width, height = im.size
            frames = getattr(im, 'n_frames', 1)
            im.seek(frames - 1)  # force-decode to the last frame
    except (UnidentifiedImageError, OSError, SyntaxError, EOFError) as e:
        raise AssertionError(f'{path}: GIF does not decode ({type(e).__name__}: {e})') from None
    assert frames >= 2, f'{path}: GIF has {frames} frame(s), expected an animation (>= 2)'
    assert width >= 300 and height >= 500, (
        f'implausible GIF dimensions: {path} is {width}x{height}; '
        'expected >= 300x500'
    )
    print(f'validated {path}: {size} bytes, {width}x{height}, {frames} frames')


def _book_generation(stamp: object, label: str) -> datetime:
    """Parse a book stamp (``2026/08/03 12:00 HKT``) into a comparable time.

    Unparseable is fatal, not skipped: an unreadable stamp would otherwise turn
    the cross-generation direction check below into a silent pass.
    """
    assert isinstance(stamp, str) and stamp.strip(), f'{label} missing'
    text = stamp.strip().removesuffix('HKT').strip()
    try:
        return datetime.strptime(text, '%Y/%m/%d %H:%M')
    except ValueError:
        raise AssertionError(f'{label} is unparseable: {stamp!r}') from None


def _assert_dashboard_money_reconciles(
        data: dict, portfolio_path: Path | str,
        fx_path: Path | str | None = None) -> None:
    """Reconcile public first-paint money against the canonical source book."""
    portfolio_path = Path(portfolio_path)
    assert portfolio_path.is_file(), f'portfolio missing: {portfolio_path}'
    try:
        portfolio = json.loads(portfolio_path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f'portfolio is not valid JSON/UTF-8: {exc}') from None

    # Reuse the same conservation rules that protect local pre-push and brief
    # generation. Only arithmetic/accounting findings are fatal here; quote
    # freshness and market-data advisories remain visible in the dashboard.
    from clawock.portfolio import integrity as preflight_integrity
    report = preflight_integrity.check(portfolio_path)
    money_findings = [
        finding for finding in report['findings']
        if finding.get('code') in DASHBOARD_MONEY_INTEGRITY_CODES
    ]
    assert not money_findings, (
        'portfolio money integrity failed: '
        + '; '.join(f"{finding['code']} {finding['msg']}"
                    for finding in money_findings[:6]))

    # The dashboard and portfolio.json have deliberately different commit
    # cadences. Mode 7 and the scheduled publisher rebuild the dashboard from
    # the live book every slot but never commit portfolio.json — that is an
    # explicit design decision (intraday_postflight.py header), because the book
    # can be mid-refresh when a postflight commits. The price updaters own it and
    # publish at open/midday/close. During a session the committed dashboard is
    # therefore legitimately built from a NEWER book than the committed
    # portfolio, and comparing their totals field by field compares two
    # generations — which reddened the gate on every intraday tick.
    #
    # Reconcile field by field only within one book generation. Across
    # generations, assert the direction instead: a dashboard built from an OLDER
    # book than the committed one is real staleness and still fails here.
    book_stamp = data.get('last_updated')
    source_stamp = portfolio.get('last_updated')
    same_book = book_stamp == source_stamp
    if not same_book:
        assert _book_generation(book_stamp, 'dashboard.last_updated') >= \
            _book_generation(source_stamp, 'portfolio.last_updated'), (
                f'dashboard was built from an older book than the committed '
                f'portfolio.json: dashboard={book_stamp} < portfolio={source_stamp}')

    def finite(value):
        return (isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value))

    def same_number(actual, expected, label, tolerance=0.005):
        assert finite(actual), f'{label} must be a finite number'
        assert finite(expected), f'portfolio source for {label} must be a finite number'
        assert abs(actual - expected) <= tolerance, (
            f'{label}={actual} does not reconcile to portfolio.json={expected}')

    def same_optional_number(actual, expected, label, tolerance=0.005):
        if expected is None:
            assert actual is None, (
                f'{label}={actual} does not reconcile to portfolio.json=null')
            return
        same_number(actual, expected, label, tolerance)

    regions = {
        'us': ('us_stocks', 'USD', {
            'value_usd': 'total_current_value',
            'cost_usd': 'total_cost',
            'pnl_usd': 'total_pnl',
            'pnl_pct': 'total_pnl_percent',
            'today_change_usd': 'today_total_change',
            'realized_usd': 'realized_pnl',
            'cash_usd': 'cash_usd',
        }),
        'hk': ('hk_stocks', 'HKD', {
            'value_hkd': 'total_current_value',
            'cost_hkd': 'total_cost',
            'pnl_hkd': 'total_pnl',
            'pnl_pct': 'total_pnl_percent',
            'today_change_hkd': 'today_total_change',
            'realized_hkd': 'realized_pnl',
            'cash_hkd': 'cash_hkd',
        }),
    }
    holding_fields = {
        'shares': ('shares', None),
        'cost_basis': ('cost_basis', 4),
        'current_price': ('current_price', 4),
        'current_value': ('current_value', 2),
        'today_change': ('today_change', 2),
        'today_change_pct': ('today_change_pct', 2),
        'day_high': ('day_high', 4),
        'day_low': ('day_low', 4),
        'pnl_abs': ('pnl_abs', 2),
        'pnl_percent': ('pnl_percent', 2),
    }

    for leg, (region, currency, total_fields) in regions.items():
        source_leg = portfolio.get('portfolios', {}).get(region)
        assert isinstance(source_leg, dict), f'portfolio missing {region}'
        public_rows = data['holdings'][leg]
        public_by_ticker = {
            row.get('ticker'): row for row in public_rows if isinstance(row, dict)
        }
        assert len(public_by_ticker) == len(public_rows), (
            f'holdings.{leg} has duplicate or malformed tickers')

        # Everything from here to the concentration card compares the published
        # view against the source book, so it is only meaningful within one book
        # generation. See the `same_book` note above.
        if same_book:
            for public_field, source_field in total_fields.items():
                same_optional_number(
                    data['totals'][leg].get(public_field),
                    source_leg.get(source_field),
                    f'totals.{leg}.{public_field}',
                )

            source_rows = {
                row.get('ticker') or row.get('code'): row
                for row in source_leg.get('holdings', [])
                if isinstance(row, dict) and (row.get('shares') or 0) > 0
            }
            assert set(public_by_ticker) == set(source_rows), (
                f'holdings.{leg} ticker coverage mismatch: '
                f'missing={sorted(set(source_rows) - set(public_by_ticker))}, '
                f'extra={sorted(set(public_by_ticker) - set(source_rows))}')

            for ticker, source in source_rows.items():
                public = public_by_ticker[ticker]
                expected_name = source.get('name') or source.get('stock_name', '')
                assert public.get('name') == expected_name, (
                    f'holdings.{leg}.{ticker}.name does not reconcile')
                assert public.get('currency') == currency, (
                    f'holdings.{leg}.{ticker}.currency must be {currency}')
                assert public.get('is_active') is True, (
                    f'holdings.{leg}.{ticker}.is_active must be true')
                assert public.get('trades_count') == len(source.get('trades') or []), (
                    f'holdings.{leg}.{ticker}.trades_count does not reconcile')
                for public_field, (source_field, places) in holding_fields.items():
                    source_value = source.get(source_field)
                    expected = (source_value if places is None
                                else round(source_value or 0, places))
                    tolerance = 1e-9 if places is None else 0.5 * (10 ** -places)
                    same_number(
                        public.get(public_field), expected,
                        f'holdings.{leg}.{ticker}.{public_field}', tolerance,
                    )

        # Recompute the public concentration card from the public holding rows.
        positive = [row for row in public_rows if row.get('current_value', 0) > 0]
        total = sum(row['current_value'] for row in positive)
        positions = [{
            'ticker': row['ticker'],
            'name': row['name'],
            'value': row['current_value'],
            'weight': round(row['current_value'] / total, 4),
        } for row in positive] if total > 0 else []
        positions.sort(key=lambda row: -row['weight'])
        expected_hhi = round(sum(row['weight'] ** 2 for row in positions), 4)
        expected_top2 = round(sum(row['weight'] for row in positions[:2]), 4)
        concentration = data['concentration'][leg]
        same_number(concentration.get('total'), round(total, 2),
                    f'concentration.{leg}.total')
        same_number(concentration.get('hhi'), expected_hhi,
                    f'concentration.{leg}.hhi', 0.00005)
        same_number(concentration.get('top2'), expected_top2,
                    f'concentration.{leg}.top2', 0.00005)
        assert concentration.get('positions') == positions, (
            f'concentration.{leg}.positions do not reconcile to holdings.{leg}')

    fx_rate = data['fx'].get('usdhkd')
    fx_source_available = fx_path is not None and Path(fx_path).is_file()
    if fx_rate is not None:
        assert finite(fx_rate) and fx_rate > 0, (
            'fx.usdhkd must be null or a positive finite number')
    if fx_source_available:
        fx_source = json.loads(Path(fx_path).read_text(encoding='utf-8'))
        same_number(fx_rate, fx_source.get('rate'), 'fx.usdhkd', 0.00005)

    embedded = (data.get('build_status') or {}).get('integrity')
    assert isinstance(embedded, dict), 'build_status.integrity missing'
    assert embedded.get('ok') is True and embedded.get('error_count') == 0, (
        'build_status.integrity is not clean')


def validate_dashboard(
        path: Path | str = 'assets/data/dashboard.json', *,
        portfolio_path: Path | str | None = None,
        fx_path: Path | str | None = None,
        overview_path: Path | str | None = None) -> None:
    """Validate the committed, public full cross-tab dashboard payload.

    This intentionally uses only the standard library so a dashboard-only push
    can fail closed on a stock GitHub runner without installing the full test
    environment. Freshness is schedule-aware in the UI and is not a schema
    property, so this gate validates the timestamp but does not compare it with
    wall-clock time.
    """
    path = Path(path)
    assert path.is_file(), f'dashboard payload missing: {path}'
    try:
        raw = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise AssertionError('file is not valid UTF-8') from None
    assert raw.strip(), 'file is empty'
    size = path.stat().st_size
    assert size < DASHBOARD_MAX_BYTES, (
        f'{size:,} bytes exceeds the {DASHBOARD_MAX_BYTES:,}-byte '
        'full dashboard cap')
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f'invalid JSON at line {exc.lineno} column {exc.colno}') from None
    assert isinstance(data, dict), 'top-level JSON must be an object'

    required = (
        'generated_at', 'fx', 'totals', 'concentration', 'holdings',
        'snapshots', 'decision_metrics', 'decision_delta',
    )
    missing = [key for key in required if key not in data]
    assert not missing, f'missing keys: {missing}'
    assert 'episode_backtest' not in data, (
        'Reflect backtest leaked into first-paint payload')

    generated_at = data['generated_at']
    assert isinstance(generated_at, str), 'generated_at missing'
    try:
        datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    except ValueError:
        raise AssertionError(
            'generated_at is not a valid ISO timestamp') from None

    assert isinstance(data['fx'], dict), 'fx must be an object'
    assert isinstance(data['totals'], dict), 'totals must be an object'
    assert isinstance(data['holdings'], dict), 'holdings must be an object'
    assert isinstance(data['concentration'], dict), (
        'concentration must be an object')
    assert isinstance(data['snapshots'], list), 'snapshots must be a list'
    assert data['snapshots'], 'snapshots is empty — dashboard would render blank'
    assert isinstance(data['decision_metrics'], dict), (
        'decision_metrics must be an object')
    assert isinstance(data['decision_delta'], dict), (
        'decision_delta must be an object')

    def finite_number(value):
        return (isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value))

    allowed_levels = {'healthy', 'moderate', 'concentrated', 'danger'}
    for leg in ('us', 'hk'):
        assert isinstance(data['totals'].get(leg), dict), (
            f'totals.{leg} must be an object')
        assert isinstance(data['holdings'].get(leg), list), (
            f'holdings.{leg} must be a list')
        concentration = data['concentration'].get(leg)
        assert isinstance(concentration, dict), (
            f'concentration.{leg} must be an object')
        required_concentration = {'hhi', 'top2', 'positions', 'total', 'verdict'}
        missing_concentration = sorted(required_concentration - concentration.keys())
        assert not missing_concentration, (
            f'concentration.{leg} missing keys: {missing_concentration}')
        for field in ('hhi', 'top2', 'total'):
            assert finite_number(concentration[field]), (
                f'concentration.{leg}.{field} must be a finite number')
        assert isinstance(concentration['positions'], list), (
            f'concentration.{leg}.positions must be a list')
        verdict = concentration['verdict']
        assert isinstance(verdict, dict), (
            f'concentration.{leg}.verdict must be an object')
        assert verdict.get('level') in allowed_levels, (
            f'concentration.{leg} has invalid verdict level')

    if portfolio_path is not None:
        _assert_dashboard_money_reconciles(data, portfolio_path, fx_path)

    if overview_path is not None:
        overview_path = Path(overview_path)
        assert overview_path.is_file(), f'Overview projection missing: {overview_path}'
        assert overview_path.stat().st_size < OVERVIEW_MAX_BYTES, (
            f'{overview_path.stat().st_size:,} bytes exceeds the '
            f'{OVERVIEW_MAX_BYTES:,}-byte Overview cap')
        overview = json.loads(overview_path.read_text(encoding='utf-8'))
        assert overview.get('schema_version') == 1, 'Overview schema_version must be 1'
        assert overview.get('projection') == 'overview', 'Overview projection kind invalid'
        assert overview.get('generation_id') == data['generated_at'], (
            'Overview/full dashboard generation mismatch')
        for field in ('generated_at', 'fx', 'totals', 'build_status'):
            assert overview.get(field) == data.get(field), (
                f'Overview {field} drifted from canonical dashboard')
        assert isinstance(overview.get('overview_equity'), list), (
            'Overview equity projection must be a list')
        assert overview['overview_equity'], 'Overview equity projection is empty'

    suffix = ' + money reconciliation' if portfolio_path is not None else ''
    print(f'dashboard structural validation{suffix} OK: {path}')


def validate_coverage_badge(path: Path | str = 'assets/data/coverage.json') -> None:
    """The README badge is rendered by shields.io straight from this file.

    A malformed payload does not break the build — it silently renders as an
    "invalid" badge on the front page, which is the exact failure this gate
    exists to catch before the commit.
    """
    path = Path(path)
    assert path.is_file(), f'coverage badge missing: {path}'
    try:
        raw = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise AssertionError('file is not valid UTF-8') from None
    assert raw.strip(), 'file is empty'
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f'invalid JSON at line {exc.lineno} column {exc.colno}') from None
    assert isinstance(data, dict), 'top-level JSON must be an object'

    # Strict shields endpoint schema: extra keys are not part of the contract, so
    # reject them here rather than discover the rendering failure on the README.
    assert set(data) == {'schemaVersion', 'label', 'message', 'color'}, (
        f'unexpected badge fields: {sorted(data)}')
    assert data['schemaVersion'] == 1, f'unsupported schemaVersion {data["schemaVersion"]!r}'
    label = data['label']
    assert isinstance(label, str) and label.strip(), 'label missing'
    color = data['color']
    assert isinstance(color, str) and color.strip(), 'color missing'

    message = data['message']
    assert isinstance(message, str), 'message must be a string'
    match = re.fullmatch(r'(\d{1,3})%', message)
    assert match, f'message is not a percentage: {message!r}'
    percent = int(match.group(1))
    # 0% and 100% are both real signals that the measurement broke rather than
    # results worth publishing (nothing instrumented / everything ignored).
    assert 0 < percent < 100, f'implausible coverage percentage: {percent}%'
    print(f'validated {path}: {label} {message}')


# The one list of what this command accepts: the CLI's `choices=` and the
# dispatch below both read it, so a new validator cannot be reachable from one
# and invisible to the other.
VALIDATORS = ('macro', 'sentiment', 'influencer', 'news-digest', 'eod-archive',
              'weekly-review', 'screenshots', 'gif', 'dashboard', 'coverage')


def _dispatch(name: str) -> None:
    os.chdir(ROOT)
    if name == 'macro':
        validate_macro('assets/data/macro.json')
    elif name == 'sentiment':
        validate_sentiment('assets/data/sentiment.json', 'portfolio.json')
    elif name == 'influencer':
        validate_influencer('assets/data/influencer_feed.json')
    elif name == 'news-digest':
        validate_news_digest('assets/data/us_news_digest.json')
    elif name == 'eod-archive':
        validate_eod_archive('memory/archive/eod-history.csv', 'portfolio.json')
    elif name == 'weekly-review':
        iso_year, iso_week, _ = date.today().isocalendar()
        week_id = f'{iso_year}-W{iso_week:02d}'
        validate_weekly_review(f'memory/weekly/{week_id}.md', week_id=week_id)
    elif name == 'screenshots':
        validate_screenshots(tuple(
            (filename, min_size, min_width, min_height)
            for filename, min_size, min_width, min_height in DEFAULT_SCREENSHOTS
        ))
    elif name == 'gif':
        validate_gif('site/assets/dashboard.gif')
    elif name == 'dashboard':
        validate_dashboard(
            'assets/data/dashboard.json',
            portfolio_path='portfolio.json',
            fx_path='.cache/fx_rate.json',
            overview_path='assets/data/overview.json',
        )
    elif name == 'coverage':
        validate_coverage_badge('assets/data/coverage.json')
    else:
        raise SystemExit(
            f'unknown validator {name!r}; choose one of: {", ".join(VALIDATORS)}')


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog='clawock validate-sidecar',
        description='Check one published artifact against its structural contract.')
    parser.add_argument('name', choices=VALIDATORS,
                        help='the artifact to validate')
    argv = [parser.parse_args(argv).name]
    try:
        _dispatch(argv[0])
    except SystemExit:
        raise
    except Exception as exc:
        failure_labels = {
            'macro': 'macro snapshot assets/data/macro.json',
            'sentiment': 'sentiment snapshot assets/data/sentiment.json',
            'influencer': 'influencer feed assets/data/influencer_feed.json',
            'news-digest': 'news digest assets/data/us_news_digest.json',
            'eod-archive': 'EOD archive memory/archive/eod-history.csv',
            'weekly-review': 'weekly review',
            'screenshots': 'screenshots',
            'gif': 'GIF site/assets/dashboard.gif',
            'dashboard': 'dashboard payload assets/data/dashboard.json',
            'coverage': 'coverage badge assets/data/coverage.json',
        }
        label = failure_labels.get(argv[0], argv[0])
        print(f'ASSERTION FAILED: {label}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
