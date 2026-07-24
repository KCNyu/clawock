#!/usr/bin/env python3
"""Behavioral coverage gates for workflow-generated sidecar artifacts."""
from __future__ import annotations

import csv
import json
import math
import os
import re
import struct
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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
    successful = [
        field for field in quote_fields
        if isinstance(data.get(field), dict)
        and finite_number(data[field].get('price'))
        and data[field]['price'] > 0
        and data[field].get('source') in quote_sources
    ]
    fear_greed = data.get('fear_greed')
    if isinstance(fear_greed, dict) and finite_number(fear_greed.get('score')):
        successful.append('fear_greed')
    fed_press = data.get('fed_press')
    if (isinstance(fed_press, list)
            and any(isinstance(item, dict) and str(item.get('title', '')).strip()
                    for item in fed_press)):
        successful.append('fed_press')

    assert successful, 'snapshot has zero successfully populated fields'
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
        result_fields = ('reddit_posts', 'google_news_en', 'google_news_zh')
        for field in result_fields:
            results = row.get(field)
            assert isinstance(results, list), f'{ticker} {field} must be a list'
            assert all(isinstance(item, dict) for item in results), (
                f'{ticker} {field} contains a malformed item')
        scanned.add(ticker)

    missing = sorted(expected - scanned)
    assert not missing, f'sentiment snapshot missing active tickers: {", ".join(missing)}'
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
        datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    except ValueError:
        raise AssertionError('generated_at is not a valid ISO timestamp') from None

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

    sources = data.get('sources')
    assert isinstance(sources, dict) and sources, 'sources missing or empty'
    assert all(isinstance(name, str) and name.strip()
               and isinstance(source, str) and source.strip()
               for name, source in sources.items()), (
        'sources must map non-empty names to non-empty descriptions')

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
    assert isinstance(tickers, list) and tickers, 'tickers missing or empty'
    assert isinstance(counts, dict), 'raw_news_counts must be an object'
    invalid_counts = [key for key, value in counts.items()
                      if not isinstance(value, int) or isinstance(value, bool)]
    assert not invalid_counts, (
        f'raw_news_counts values must be integers: {invalid_counts}')
    total_news = sum(counts.values())
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
    if portfolio_path.is_file():
        portfolio = json.loads(portfolio_path.read_text(encoding='utf-8'))
        expected = {
            holding['ticker']
            for region in ('us_stocks', 'hk_stocks')
            for holding in portfolio['portfolios'].get(region, {}).get('holdings', [])
            if holding.get('shares', 0) > 0
        }
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
    print(f'EOD archive coverage validation OK: {len(today_rows)} rows for {snapshot_date}')


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
    required_sections = ('本周净值', '风险演变', '下周关注')
    normalized_body = re.sub(
        r'下周(?:\s*\([^\n)]*\))?\s*关注', '下周关注', body)
    missing = [section for section in required_sections if section not in normalized_body]
    assert not missing, f'weekly review missing required sections: {missing}'
    calibration_tokens = ('Brier', '校准误差', 'Calibration', '兑现')
    assert any(token in body for token in calibration_tokens), (
        f'weekly review missing decisions/calibration section; expected any of: '
        f'{calibration_tokens}')
    headings = [line for line in body.splitlines() if line.lstrip().startswith('#')]
    assert len(headings) >= 4, 'weekly review does not contain four markdown sections'
    print(f'weekly review validation OK: {path} ({len(body)} chars)')


DEFAULT_SCREENSHOTS = (
    ('assets/shadow-backtest.png', 20_000, 400, 200),
    ('assets/social-card.png', 150_000, 1_000, 500),
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
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise AssertionError(f'{label}: PNG does not decode ({type(e).__name__}: {e})') from None


def validate_gif(path: Path | str = 'assets/dashboard.gif') -> None:
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
        validate_gif('assets/dashboard.gif')
    else:
        choices = ('macro', 'sentiment', 'influencer', 'news-digest',
                   'eod-archive', 'weekly-review', 'screenshots', 'gif')
        raise SystemExit(f'unknown validator {name!r}; choose one of: {", ".join(choices)}')


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('usage: validate_sidecars.py <name>', file=sys.stderr)
        return 2
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
            'gif': 'GIF assets/dashboard.gif',
        }
        label = failure_labels.get(argv[0], argv[0])
        print(f'ASSERTION FAILED: {label}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
