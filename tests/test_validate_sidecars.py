"""Direct behavioral tests for workflow sidecar coverage gates."""
from __future__ import annotations

import csv
import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.data import validate_sidecars as validators


ROOT = Path(__file__).resolve().parents[1]
GENERATED = '2026-07-17T00:00:00+00:00'
EOD_FIELDS = (
    'date', 'ticker', 'name', 'currency', 'shares', 'cost_basis',
    'current_price', 'pnl_pct', 'current_value',
)


def write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def write_portfolio(path: Path, tickers: tuple[str, ...]) -> Path:
    holdings = [{'ticker': ticker, 'shares': 1} for ticker in tickers]
    return write_json(path, {
        'portfolios': {
            'us_stocks': {'holdings': holdings},
            'hk_stocks': {'holdings': []},
        },
    })


def sentiment_payload(tickers: tuple[str, ...]) -> dict:
    return {
        'generated_at': GENERATED,
        'sources': ['reddit', 'google_news'],
        'tickers': [
            {
                'ticker': ticker,
                'name': ticker,
                'region': 'us_stocks',
                'reddit_mentions_7d': 0,
                'reddit_posts': [],
                'google_news_en': [],
                'google_news_zh': [],
            }
            for ticker in tickers
        ],
    }


def influencer_payload(*, items=None) -> dict:
    items = [] if items is None else items
    return {
        'generated_at': GENERATED,
        'items': items,
        'sources': {'truth_social': 'RSS feed'},
        'counts': {
            'held_hits': 0,
            'new_ideas': 0,
            'sector_hits': 0,
            'total': len(items),
        },
        'held_hits': [],
        'new_ideas': [],
        'sector_hits': [],
    }


def macro_payload(generated_at: str = GENERATED) -> dict:
    return {
        'generated_at': generated_at,
        'vix': {'price': 16.5, 'source': 'yahoo'},
        'fear_greed': None,
        'fed_press': None,
    }


def news_payload(generated_at: str = GENERATED) -> dict:
    return {
        'generated_at': generated_at,
        'tickers': ['AAPL'],
        'raw_news_counts': {'AAPL': 1},
        'digest_markdown': '### AAPL\n' + 'material digest ' * 10,
    }


def write_eod(path: Path, snapshot_date: str, tickers: tuple[str, ...]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=EOD_FIELDS)
        writer.writeheader()
        for ticker in tickers:
            writer.writerow({
                'date': snapshot_date,
                'ticker': ticker,
                'name': ticker,
                'currency': 'USD',
                'shares': 1,
                'cost_basis': 10,
                'current_price': 11,
                'pnl_pct': 10,
                'current_value': 11,
            })
    return path


def weekly_review(week_id: str, token: str) -> str:
    body = '\n'.join((
        '# 本周净值',
        '本周组合回顾。',
        '## 决策校准',
        f'{token} 指标与决策回看。',
        '## 风险演变',
        '风险与仓位演变。',
        '## 下周 (07/20-07/24) 关注',
        '下周触发条件与关注事项。',
        'x' * 1100,
    ))
    return f'---\nlayout: default\ntitle: 周复盘 · {week_id}\n---\n{body}\n'


def generated_time(path: Path) -> datetime:
    value = json.loads(path.read_text(encoding='utf-8'))['generated_at']
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def test_real_committed_macro_passes():
    macro = ROOT / 'assets/data/macro.json'
    validators.validate_macro(macro, now=generated_time(macro) + timedelta(hours=1))


def test_real_committed_sentiment_passes():
    validators.validate_sentiment(
        ROOT / 'assets/data/sentiment.json', ROOT / 'portfolio.json')


def test_real_committed_influencer_passes():
    validators.validate_influencer(ROOT / 'assets/data/influencer_feed.json')


def test_real_committed_news_digest_passes():
    news = ROOT / 'assets/data/us_news_digest.json'
    validators.validate_news_digest(news, now=generated_time(news) + timedelta(hours=1))


@pytest.mark.parametrize('header', ['## Top 移动信号', '### Top 移动信号'])
def test_news_digest_accepts_h2_and_h3_headers(tmp_path, header):
    """2026-07-21: MiniMax M3 switched the section headers from `### ` to `## `
    with otherwise-perfect content, and the literal `### ` check failed the digest
    for 3 days. Both levels must pass."""
    payload = news_payload()
    payload['digest_markdown'] = (
        f'{header}\n'
        '- SPCX: SpaceX IPO 限售解锁,supply overhang 风险,减仓或对冲\n'
        '- SKHY: 财报前动能强但预期已高,谨防 buy rumor sell fact\n')
    snapshot = write_json(tmp_path / 'news.json', payload)
    validators.validate_news_digest(
        snapshot, now=generated_time(snapshot) + timedelta(hours=1))


@pytest.mark.parametrize('bad,problem', [
    ('一段没有任何 markdown 结构的散文，' * 8, 'no h2/h3 markdown header'),
    ('## Only a header\n没有要点，只有一段话。' * 4, 'no bullet points'),
])
def test_news_digest_rejects_structureless_output(tmp_path, bad, problem):
    """The gate must still catch a prose wall / refusal — accepting h2 only
    loosens the header level, not the requirement for structure."""
    payload = news_payload()
    payload['digest_markdown'] = bad
    snapshot = write_json(tmp_path / 'news.json', payload)
    with pytest.raises(AssertionError, match=problem):
        validators.validate_news_digest(
            snapshot, now=generated_time(snapshot) + timedelta(hours=1))


def test_real_committed_eod_archive_passes(tmp_path):
    archive = ROOT / 'memory/archive/eod-history.csv'
    with archive.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    latest_date = max(row['date'] for row in rows)
    latest_tickers = tuple(row['ticker'] for row in rows if row['date'] == latest_date)
    archive_portfolio = write_portfolio(tmp_path / 'archive-portfolio.json', latest_tickers)
    validators.validate_eod_archive(
        archive, archive_portfolio, snapshot_date=latest_date)


def test_real_committed_weekly_review_passes():
    weekly = max((ROOT / 'memory/weekly').glob('*.md'))
    validators.validate_weekly_review(weekly)


def test_real_committed_screenshots_pass():
    validators.validate_screenshots(tuple(
        (ROOT / filename, min_size, min_width, min_height)
        for filename, min_size, min_width, min_height in validators.DEFAULT_SCREENSHOTS
    ))


def test_real_committed_gif_passes():
    validators.validate_gif(ROOT / 'assets/dashboard.gif')


JSON_VALIDATORS = (
    ('macro', lambda path, portfolio: validators.validate_macro(
        path, now=datetime(2026, 7, 17, 1, tzinfo=timezone.utc))),
    ('sentiment', lambda path, portfolio: validators.validate_sentiment(path, portfolio)),
    ('influencer', lambda path, portfolio: validators.validate_influencer(path)),
    ('news', lambda path, portfolio: validators.validate_news_digest(
        path, now=datetime(2026, 7, 17, 1, tzinfo=timezone.utc))),
)


@pytest.mark.parametrize('name,validator', JSON_VALIDATORS)
@pytest.mark.parametrize(
    'content,problem',
    ((b'', 'file is empty'),
     (b'{', 'invalid JSON at line 1 column 2'),
     (b'[]', 'top-level JSON must be an object'),
     (b'\xff\xfe', 'file is not valid UTF-8')),
)
def test_json_artifacts_fail_clearly(
        tmp_path, name, validator, content, problem):
    path = tmp_path / f'{name}.json'
    path.write_bytes(content)
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL',))

    with pytest.raises(AssertionError, match=problem):
        validator(path, portfolio)


def test_sentiment_quiet_day_with_zero_results_passes(tmp_path):
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL',))
    snapshot = write_json(tmp_path / 'sentiment.json', sentiment_payload(('AAPL',)))

    validators.validate_sentiment(snapshot, portfolio)


def test_influencer_quiet_day_with_zero_items_passes(tmp_path):
    feed = write_json(tmp_path / 'influencer.json', influencer_payload())

    validators.validate_influencer(feed)


def test_sentiment_missing_active_ticker_fails(tmp_path):
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL', 'MSFT'))
    snapshot = write_json(tmp_path / 'sentiment.json', sentiment_payload(('AAPL',)))

    with pytest.raises(
            AssertionError,
            match='sentiment snapshot missing active tickers: MSFT'):
        validators.validate_sentiment(snapshot, portfolio)


@pytest.mark.parametrize(
    'validator,payload',
    ((validators.validate_macro, macro_payload),
     (validators.validate_news_digest, news_payload)),
)
def test_24_hour_stale_generated_at_fails(tmp_path, validator, payload):
    path = write_json(tmp_path / 'artifact.json', payload())
    now = datetime.fromisoformat(GENERATED) + timedelta(hours=24)

    with pytest.raises(AssertionError, match='age 24.00h exceeds 18h'):
        validator(path, now=now)


def test_all_cash_portfolio_passes_without_archive(tmp_path, capsys):
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ())

    validators.validate_eod_archive(
        tmp_path / 'missing.csv', portfolio, snapshot_date='2026-07-17')

    assert capsys.readouterr().out == (
        'EOD archive coverage validation OK: all-cash portfolio, '
        '0 rows for 2026-07-17\n')


def test_eod_missing_active_ticker_fails(tmp_path):
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL', 'MSFT'))
    archive = write_eod(tmp_path / 'eod.csv', '2026-07-17', ('AAPL',))

    with pytest.raises(
            AssertionError,
            match='EOD archive missing active tickers for 2026-07-17: MSFT'):
        validators.validate_eod_archive(
            archive, portfolio, snapshot_date='2026-07-17')


def test_eod_zero_price_fails(tmp_path):
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL',))
    archive = write_eod(tmp_path / 'eod.csv', '2026-07-17', ('AAPL',))
    rows = archive.read_text(encoding='utf-8').replace(',11,10,11\n', ',0,10,11\n')
    archive.write_text(rows, encoding='utf-8')

    with pytest.raises(AssertionError, match='invalid EOD current_price for AAPL'):
        validators.validate_eod_archive(
            archive, portfolio, snapshot_date='2026-07-17')


@pytest.mark.parametrize('invalid_count', ('1', None))
def test_news_counts_reject_non_integer_before_sum(tmp_path, invalid_count):
    payload = news_payload()
    payload['raw_news_counts']['AAPL'] = invalid_count
    path = write_json(tmp_path / 'digest.json', payload)

    with pytest.raises(AssertionError, match='raw_news_counts values must be integers'):
        validators.validate_news_digest(
            path, now=datetime(2026, 7, 17, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize('field,value', (
    ('author', None), ('author', 7), ('text', None), ('text', 7),
))
def test_influencer_items_require_real_nonempty_strings(
        tmp_path, field, value):
    item = {'author': 'Trump', 'text': 'market statement', 'relevance': 0.5}
    item[field] = value
    feed = write_json(tmp_path / 'influencer.json', influencer_payload(items=[item]))

    with pytest.raises(AssertionError, match=f'item 0 missing {field}'):
        validators.validate_influencer(feed)


@pytest.mark.parametrize(
    'quote',
    ({'price': 0, 'source': 'yahoo'},
     {'price': 1, 'source': 'placeholder'}),
)
def test_macro_quote_failure_markers_do_not_count_as_coverage(tmp_path, quote):
    payload = macro_payload()
    payload['vix'] = quote
    path = write_json(tmp_path / 'macro.json', payload)

    with pytest.raises(
            AssertionError,
            match='snapshot has zero successfully populated fields'):
        validators.validate_macro(
            path, now=datetime(2026, 7, 17, 1, tzinfo=timezone.utc))


def test_eod_short_row_reports_malformed_ticker(tmp_path, capsys):
    archive = tmp_path / 'eod.csv'
    archive.write_text(','.join(EOD_FIELDS) + '\n2026-07-17\n', encoding='utf-8')
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL',))

    with pytest.raises(SystemExit, match='1'):
        validators.validate_eod_archive(
            archive, portfolio, snapshot_date='2026-07-17')

    assert 'malformed row 1 for 2026-07-17: ticker missing' in capsys.readouterr().err


@pytest.mark.parametrize('token', ('Brier', '校准误差', 'Calibration', '兑现'))
def test_weekly_calibration_token_and_next_week_variants_pass(tmp_path, token):
    path = tmp_path / '2026-W29.md'
    path.write_text(weekly_review('2026-W29', token), encoding='utf-8')

    validators.validate_weekly_review(path)


def _weekly(week_id, body):
    return f'---\nlayout: default\ntitle: 周复盘 · {week_id}\n---\n{body}\n'


def test_weekly_accepts_all_english_headers(tmp_path):
    """2026-07 audit: MiniMax M3 drifted to English section headers; the committed
    2026-W24.md uses `## Weekly NAV / Plan Adherence & Calibration / Risk Evolution
    / Next Week's Focus` and the old literal-ZH-token gate rejected it."""
    body = '\n'.join((
        '## Executive Summary', 'Overview.',
        '## 1. Weekly NAV: Drawdown', 'Start vs end NAV analysis.',
        '## 2. Plan Adherence & Calibration', 'Brier score and adherence.',
        '## 3. Risk Evolution', 'Beta/Vol/Sharpe trend.',
        "## 4. Next Week's Focus", 'Three actionable triggers.',
        'x' * 1100))
    path = tmp_path / '2026-W24.md'
    path.write_text(_weekly('2026-W24', body), encoding='utf-8')
    validators.validate_weekly_review(path)


def test_weekly_accepts_bold_labels_without_hash_headings(tmp_path):
    """The generator prompt asks for `**本周净值**`-style BOLD labels, not `#`
    headings — a review that follows the prompt literally must not be failed by a
    heading-count check."""
    body = '\n'.join((
        '**本周净值**', '组合回顾与净值。',
        '**决策兑现**', 'Brier 与决策回看。',
        '**风险演变**', '风险与仓位演变。',
        '**下周关注**', '下周触发条件。',
        'x' * 1100))
    path = tmp_path / '2026-W30.md'
    path.write_text(_weekly('2026-W30', body), encoding='utf-8')
    validators.validate_weekly_review(path)


def test_weekly_still_rejects_a_genuinely_missing_section(tmp_path):
    """Loosening the language must not loosen the requirement: a review with no
    risk section (any language) still fails, and the error names it."""
    body = '\n'.join((
        '## Weekly NAV', 'NAV analysis.',
        '## Plan Adherence & Calibration', 'Brier and adherence.',
        "## Next Week's Focus", 'Triggers.',
        'x' * 1100))  # no risk-evolution section at all
    path = tmp_path / '2026-W31.md'
    path.write_text(_weekly('2026-W31', body), encoding='utf-8')
    with pytest.raises(AssertionError, match='风险演变'):
        validators.validate_weekly_review(path)


def test_header_only_png_is_rejected_by_size_floor(tmp_path):
    path = tmp_path / 'image.png'
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR' + struct.pack('>II', 1200, 630))

    with pytest.raises(AssertionError, match='screenshot too small'):
        validators.validate_screenshots(((path, 150_000, 1_000, 500),))


def test_header_only_gif_is_rejected_by_size_floor(tmp_path):
    path = tmp_path / 'image.gif'
    path.write_bytes(b'GIF89a' + struct.pack('<HH', 300, 500))

    with pytest.raises(AssertionError, match='GIF too small'):
        validators.validate_gif(path)


def test_large_png_with_invalid_magic_is_rejected(tmp_path):
    path = tmp_path / 'image.png'
    path.write_bytes(b'not-png!' + b'\x00' * 20_000)

    with pytest.raises(AssertionError, match='invalid PNG magic'):
        validators.validate_screenshots(((path, 20_000, 400, 200),))


def test_large_png_with_implausible_dimensions_is_rejected(tmp_path):
    path = tmp_path / 'image.png'
    header = (
        b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR'
        + struct.pack('>II', 399, 199)
    )
    path.write_bytes(header + b'\x00' * 20_000)

    with pytest.raises(AssertionError, match='implausible screenshot dimensions'):
        validators.validate_screenshots(((path, 20_000, 400, 200),))


def test_large_gif_with_invalid_magic_is_rejected(tmp_path):
    path = tmp_path / 'image.gif'
    path.write_bytes(b'NOTGIF' + struct.pack('<HH', 640, 1376) + b'\x00' * 300_000)

    with pytest.raises(AssertionError, match='invalid GIF magic'):
        validators.validate_gif(path)


def test_large_gif_with_implausible_dimensions_is_rejected(tmp_path):
    path = tmp_path / 'image.gif'
    path.write_bytes(b'GIF89a' + struct.pack('<HH', 299, 499) + b'\x00' * 300_000)

    with pytest.raises(AssertionError, match='implausible GIF dimensions'):
        validators.validate_gif(path)
