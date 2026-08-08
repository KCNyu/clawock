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


def influencer_payload(*, items=None, source_status=None) -> dict:
    items = [] if items is None else items
    payload = {
        'generated_at': GENERATED,
        'lookback_hours': 48,
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
    if source_status is not None:
        payload['source_status'] = source_status
    return payload


def macro_payload(generated_at: str = GENERATED) -> dict:
    return {
        'generated_at': generated_at,
        'vix': {'price': 16.5, 'source': 'yahoo'},
        'fear_greed': None,
        'fed_press': None,
    }


def dashboard_payload() -> dict:
    return {
        'generated_at': GENERATED,
        'fx': {'usdhkd': 7.8, 'source': 'test', 'fetched_at': GENERATED},
        'totals': {'us': {}, 'hk': {}},
        'holdings': {'us': [], 'hk': []},
        'concentration': {
            leg: {
                'hhi': 0.0,
                'top2': 0.0,
                'positions': [],
                'total': 0.0,
                'verdict': {'level': 'healthy'},
            }
            for leg in ('us', 'hk')
        },
        'snapshots': [{'date': '2026-07-17'}],
        'decision_metrics': {},
        'decision_delta': {},
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


def test_news_digest_accepts_explicit_no_material_news(tmp_path):
    payload = {
        'generated_at': GENERATED,
        'lookback_hours': 48,
        'tickers': ['AAPL'],
        'raw_news_counts': {'AAPL': 0},
        'digest_markdown': '',
        'news_source_per_ticker': {'AAPL': 'none'},
        'source_status': {
            'AAPL': {
                'finnhub': 'failed',
                'google_news': 'success_empty',
            },
        },
        'no_material_news': True,
    }
    snapshot = write_json(tmp_path / 'news.json', payload)

    validators.validate_news_digest(
        snapshot, now=generated_time(snapshot) + timedelta(hours=1))


def test_no_material_news_without_successful_empty_source_fails(tmp_path):
    payload = {
        'generated_at': GENERATED,
        'lookback_hours': 48,
        'tickers': ['AAPL'],
        'raw_news_counts': {'AAPL': 0},
        'digest_markdown': '',
        'source_status': {
            'AAPL': {'finnhub': 'failed', 'google_news': 'failed'},
        },
        'no_material_news': True,
    }
    snapshot = write_json(tmp_path / 'news.json', payload)

    with pytest.raises(
            AssertionError,
            match='no_material_news has no successful empty source'):
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
    validators.validate_gif(ROOT / 'site/assets/dashboard.gif')


def test_real_committed_dashboard_passes(freshly_built_dashboard):
    validators.validate_dashboard(
        freshly_built_dashboard, portfolio_path=ROOT / 'portfolio.json')


@pytest.mark.parametrize('mutation,problem', (
    (lambda payload: payload['holdings']['us'][0].update(current_value=-999),
     r'holdings\.us\..*\.current_value=.*does not reconcile'),
    (lambda payload: payload['totals']['hk'].update(pnl_hkd=-999),
     r'totals\.hk\.pnl_hkd=.*does not reconcile'),
    (lambda payload: payload['holdings']['us'].pop(),
     r'holdings\.us ticker coverage mismatch'),
    (lambda payload: payload['concentration']['us'].update(hhi=0.9999),
     r'concentration\.us\.hhi=.*does not reconcile'),
    (lambda payload: payload['build_status']['integrity'].update(ok=False),
     r'build_status\.integrity is not clean'),
))
def test_dashboard_money_reconciliation_rejects_public_drift(
        tmp_path, freshly_built_dashboard, mutation, problem):
    payload = json.loads(freshly_built_dashboard.read_text())
    mutation(payload)
    dashboard = write_json(tmp_path / 'dashboard.json', payload)

    with pytest.raises(AssertionError, match=problem):
        validators.validate_dashboard(
            dashboard, portfolio_path=ROOT / 'portfolio.json')


def _book(payload, stamp):
    payload['last_updated'] = stamp
    return payload


def test_intraday_dashboard_ahead_of_the_committed_book_is_not_a_failure(
        tmp_path, freshly_built_dashboard):
    """The intraday publishing model: every slot rebuilds the dashboard from the
    live book, but portfolio.json is committed only at open/midday/close. The
    committed dashboard is then legitimately a newer generation, and comparing
    the two field by field reddened the gate on every tick of 2026-08-03."""
    portfolio = json.loads((ROOT / 'portfolio.json').read_text())
    source = write_json(
        tmp_path / 'portfolio.json', _book(portfolio, '2026/08/03 09:30 HKT'))

    payload = json.loads(freshly_built_dashboard.read_text())
    payload['last_updated'] = '2026/08/03 12:00 HKT'
    payload['totals']['hk']['value_hkd'] += 1688.0
    dashboard = write_json(tmp_path / 'dashboard.json', payload)

    validators.validate_dashboard(dashboard, portfolio_path=source)


def test_dashboard_built_from_an_older_book_than_the_committed_one_fails(
        tmp_path, freshly_built_dashboard):
    portfolio = json.loads((ROOT / 'portfolio.json').read_text())
    source = write_json(
        tmp_path / 'portfolio.json', _book(portfolio, '2026/08/03 12:00 HKT'))

    payload = json.loads(freshly_built_dashboard.read_text())
    payload['last_updated'] = '2026/08/03 09:30 HKT'
    dashboard = write_json(tmp_path / 'dashboard.json', payload)

    with pytest.raises(AssertionError, match='older book than the committed'):
        validators.validate_dashboard(dashboard, portfolio_path=source)


def test_same_book_still_reconciles_field_by_field(tmp_path, freshly_built_dashboard):
    """The relaxation above must not reach inside a single generation."""
    payload = json.loads(freshly_built_dashboard.read_text())
    payload['totals']['hk']['value_hkd'] += 1688.0
    dashboard = write_json(tmp_path / 'dashboard.json', payload)

    with pytest.raises(AssertionError, match=r'totals\.hk\.value_hkd'):
        validators.validate_dashboard(
            dashboard, portfolio_path=ROOT / 'portfolio.json')


def test_dashboard_money_reconciliation_rejects_source_integrity_failure(
        tmp_path, freshly_built_dashboard):
    portfolio = json.loads((ROOT / 'portfolio.json').read_text())
    portfolio['portfolios']['us_stocks']['total_pnl'] += 100
    source = write_json(tmp_path / 'portfolio.json', portfolio)

    with pytest.raises(AssertionError, match='portfolio money integrity failed: PNL_TOTAL'):
        validators.validate_dashboard(
            freshly_built_dashboard, portfolio_path=source)


def test_dashboard_money_reconciliation_checks_fx_cache_when_available(
        tmp_path, freshly_built_dashboard):
    fx = write_json(tmp_path / 'fx.json', {'rate': 7.0})

    with pytest.raises(AssertionError, match=r'fx\.usdhkd'):
        validators.validate_dashboard(
            freshly_built_dashboard,
            portfolio_path=ROOT / 'portfolio.json',
            fx_path=fx,
        )


def test_dashboard_money_reconciliation_allows_untracked_cash_as_null(
        tmp_path, freshly_built_dashboard):
    payload = json.loads(freshly_built_dashboard.read_text())
    portfolio = json.loads((ROOT / 'portfolio.json').read_text())
    payload['totals']['hk']['cash_hkd'] = None
    portfolio['portfolios']['hk_stocks']['cash_hkd'] = None
    dashboard = write_json(tmp_path / 'dashboard.json', payload)
    source = write_json(tmp_path / 'portfolio.json', portfolio)

    validators.validate_dashboard(dashboard, portfolio_path=source)


JSON_VALIDATORS = (
    ('macro', lambda path, portfolio: validators.validate_macro(
        path, now=datetime(2026, 7, 17, 1, tzinfo=timezone.utc))),
    ('sentiment', lambda path, portfolio: validators.validate_sentiment(path, portfolio)),
    ('influencer', lambda path, portfolio: validators.validate_influencer(path)),
    ('news', lambda path, portfolio: validators.validate_news_digest(
        path, now=datetime(2026, 7, 17, 1, tzinfo=timezone.utc))),
    ('dashboard', lambda path, portfolio: validators.validate_dashboard(path)),
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


@pytest.mark.parametrize('missing', (
    'generated_at', 'fx', 'totals', 'holdings', 'concentration', 'snapshots',
    'decision_metrics', 'decision_delta',
))
def test_dashboard_rejects_missing_first_paint_contract_key(tmp_path, missing):
    payload = dashboard_payload()
    payload.pop(missing)
    path = write_json(tmp_path / 'dashboard.json', payload)

    with pytest.raises(AssertionError, match='missing keys'):
        validators.validate_dashboard(path)


@pytest.mark.parametrize('mutation,problem', (
    (lambda payload: payload.update(generated_at='not-a-date'),
     'generated_at is not a valid ISO timestamp'),
    (lambda payload: payload['holdings'].update(us={}),
     'holdings.us must be a list'),
    (lambda payload: payload['concentration']['hk'].pop('top2'),
     'concentration.hk missing keys'),
    (lambda payload: payload['concentration']['us']['verdict'].update(level='unknown'),
     'concentration.us has invalid verdict level'),
    (lambda payload: payload.update(snapshots=[]),
     'snapshots is empty'),
    (lambda payload: payload.update(episode_backtest={}),
     'Reflect backtest leaked into first-paint payload'),
))
def test_dashboard_rejects_incomplete_or_unsafe_payload(
        tmp_path, mutation, problem):
    payload = dashboard_payload()
    mutation(payload)
    path = write_json(tmp_path / 'dashboard.json', payload)

    with pytest.raises(AssertionError, match=problem):
        validators.validate_dashboard(path)


def test_dashboard_rejects_payload_at_or_above_first_paint_cap(tmp_path):
    payload = dashboard_payload()
    payload['padding'] = 'x' * validators.DASHBOARD_MAX_BYTES
    path = write_json(tmp_path / 'dashboard.json', payload)

    with pytest.raises(AssertionError, match='full dashboard cap'):
        validators.validate_dashboard(path)


def test_sentiment_quiet_day_with_zero_results_passes(tmp_path):
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL',))
    payload = sentiment_payload(('AAPL',))
    payload['source_status'] = {'reddit': 'ok', 'google_news': 'failed'}
    snapshot = write_json(tmp_path / 'sentiment.json', payload)

    validators.validate_sentiment(snapshot, portfolio)


def test_sentiment_all_source_outage_with_zero_results_fails(tmp_path):
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL',))
    payload = sentiment_payload(('AAPL',))
    payload['source_status'] = {'reddit': 'failed', 'google_news': 'failed'}
    snapshot = write_json(tmp_path / 'sentiment.json', payload)

    with pytest.raises(AssertionError, match='sentiment: all sources failed'):
        validators.validate_sentiment(snapshot, portfolio)


def test_sentiment_legacy_snapshot_without_source_status_still_passes(tmp_path):
    portfolio = write_portfolio(tmp_path / 'portfolio.json', ('AAPL',))
    snapshot = write_json(tmp_path / 'sentiment.json', sentiment_payload(('AAPL',)))

    validators.validate_sentiment(snapshot, portfolio)


def test_influencer_quiet_day_with_zero_items_passes(tmp_path):
    feed = write_json(tmp_path / 'influencer.json', influencer_payload(
        source_status={
            'trump': 'success_empty',
            'musk': 'success_empty',
            'serenity': 'failed',
        }))

    validators.validate_influencer(feed)


def test_influencer_all_source_outage_with_zero_items_fails(tmp_path):
    feed = write_json(tmp_path / 'influencer.json', influencer_payload(
        source_status={
            'trump': 'failed',
            'musk': 'failed',
            'serenity': 'failed',
        }))

    with pytest.raises(AssertionError, match='influencer: all sources failed'):
        validators.validate_influencer(feed)


def test_influencer_stale_retained_item_fails(tmp_path):
    item = {
        'author': 'Trump',
        'text': 'market statement',
        'published': '2026-07-14T23:00:00+00:00',
        'retained_from_previous': True,
        'relevance': None,
    }
    feed = write_json(tmp_path / 'influencer.json', influencer_payload(
        items=[item],
        source_status={
            'trump': 'failed',
            'musk': 'failed',
            'serenity': 'failed',
        }))

    with pytest.raises(
            AssertionError,
            match='retained item 0 exceeds declared lookback window'):
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
            match='snapshot has zero successful market quotes'):
        validators.validate_macro(
            path, now=datetime(2026, 7, 17, 1, tzinfo=timezone.utc))


def test_macro_supplemental_sources_cannot_replace_market_quotes(tmp_path):
    payload = macro_payload()
    payload['vix'] = None
    payload['fear_greed'] = {'score': 55}
    payload['fed_press'] = [{'title': 'Federal Reserve press release'}]
    path = write_json(tmp_path / 'macro.json', payload)

    with pytest.raises(
            AssertionError,
            match='snapshot has zero successful market quotes'):
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


def test_weekly_rejects_inline_bold_counterfeit_without_real_section_markers(tmp_path):
    """2026-07 review: aliases matched anywhere in the body let a counterfeit with
    four inline mentions pass. Each concept must tie to a DISTINCT section marker
    (line-start heading or bold label). Real `**bold**` labels used inline
    mid-sentence must not count."""
    body = '\n'.join((
        '# Summary',
        'This week we discussed **navigation** of the portfolio and **calibration** '
        'of risk appetite, a **nav** overview woven into **next week** thoughts.',
        'x' * 1100))
    path = tmp_path / '2026-W40.md'
    path.write_text(_weekly('2026-W40', body), encoding='utf-8')
    with pytest.raises(AssertionError, match='missing required section marker'):
        validators.validate_weekly_review(path)


def test_weekly_rejects_generic_headings_that_are_not_the_required_sections(tmp_path):
    """2026-07 re-review: bare 净值/校准/风险/下周 fragments matched unrelated
    headings. `## 风险提示` (risk warning) is not 风险演变; `## 净值口径说明` is not
    the NAV section; `## Next Week Calendar` is not necessarily 下周关注."""
    body = '\n'.join((
        '## 净值口径说明', 'p',
        '## Model Calibration Method', 'p',
        '## 风险提示', 'p',
        '## Next Week Calendar', 'p',
        'x' * 1100))
    path = tmp_path / '2026-W44.md'
    path.write_text(_weekly('2026-W44', body), encoding='utf-8')
    # fails on NAV/净值 and 风险演变 (neither generic heading is the real section)
    with pytest.raises(AssertionError, match='NAV/净值|风险演变'):
        validators.validate_weekly_review(path)


def test_weekly_rejects_fully_english_generic_counterfeit(tmp_path):
    """2026-07 round-3 review: bare English aliases (nav/calibration/next week/
    risk trend) let an all-English counterfeit pass. English aliases are now
    contextual phrases."""
    body = '\n'.join((
        '## NAV Methodology', 'p',
        '## Model Calibration Method', 'p',
        '## Risk Trend Definitions', 'p',
        '## Next Week Calendar', 'p',
        'x' * 1100))
    path = tmp_path / '2026-W46.md'
    path.write_text(_weekly('2026-W46', body), encoding='utf-8')
    with pytest.raises(AssertionError, match='missing required section marker'):
        validators.validate_weekly_review(path)


def test_weekly_nav_requires_weekly_context_not_bare_nav(tmp_path):
    """A review valid except a `## NAV Methodology` heading fails on NAV — the real
    section is 'Weekly NAV', bare 'nav' matched unrelated headings."""
    body = '\n'.join(('## NAV Methodology', 'p', '## Plan Adherence & Calibration', 'p',
                      '## Risk Evolution', 'p', "## Next Week's Focus", 'p', 'x' * 1100))
    p = tmp_path / '2026-W49.md'
    p.write_text(_weekly('2026-W49', body), encoding='utf-8')
    with pytest.raises(AssertionError, match='NAV/净值'):
        validators.validate_weekly_review(p)


def test_weekly_calibration_requires_plan_or_decision_context(tmp_path):
    """`Plan Adherence & Calibration` passes; a bare `Model Calibration Method`
    heading does not satisfy the 决策/校准 section."""
    def review(cal_heading, week):
        body = '\n'.join(('## Weekly NAV', 'p', f'## {cal_heading}', 'p',
                          '## Risk Evolution', 'p', "## Next Week's Focus", 'p', 'x' * 1100))
        p = tmp_path / f'{week}.md'
        p.write_text(_weekly(week, body), encoding='utf-8')
        return p

    validators.validate_weekly_review(review('Plan Adherence & Calibration', '2026-W47'))
    with pytest.raises(AssertionError, match='决策/校准'):
        validators.validate_weekly_review(review('Model Calibration Method', '2026-W48'))


def test_weekly_risk_warning_heading_alone_does_not_satisfy_risk_evolution(tmp_path):
    """Pin the 风险 tightening: a review that is otherwise complete but has only a
    `## 风险提示` (risk warning) instead of a risk-evolution section fails on it."""
    body = '\n'.join((
        '## 本周净值', 'p',
        '## 决策校准', 'Brier',
        '## 风险提示', 'p',      # NOT 风险演变
        '## 下周关注', 'p',
        'x' * 1100))
    path = tmp_path / '2026-W45.md'
    path.write_text(_weekly('2026-W45', body), encoding='utf-8')
    with pytest.raises(AssertionError, match='风险演变'):
        validators.validate_weekly_review(path)


def test_weekly_word_boundary_navigation_does_not_satisfy_nav(tmp_path):
    """'navigation' in a heading must not count as the NAV section."""
    body = '\n'.join((
        '## Portfolio Navigation Notes', 'Prose.',
        '## Plan Adherence & Calibration', 'Brier prose.',
        '## Risk Evolution', 'Prose.',
        "## Next Week's Focus", 'Prose.',
        'x' * 1100))
    path = tmp_path / '2026-W41.md'
    path.write_text(_weekly('2026-W41', body), encoding='utf-8')
    with pytest.raises(AssertionError, match='NAV/净值'):
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
    # A REAL (decodable) but too-small PNG: decode passes, the dimension floor is
    # what rejects it. (Decode now runs first, so a fake header at these dims would
    # fail decode, not the dimension check.)
    from PIL import Image
    path = tmp_path / 'image.png'
    Image.new('RGB', (399, 199), 'white').save(path, 'PNG')
    with pytest.raises(AssertionError, match='implausible screenshot dimensions'):
        validators.validate_screenshots(((path, 100, 400, 200),))


def test_large_gif_with_invalid_magic_is_rejected(tmp_path):
    path = tmp_path / 'image.gif'
    path.write_bytes(b'NOTGIF' + struct.pack('<HH', 640, 1376) + b'\x00' * 300_000)

    with pytest.raises(AssertionError, match='invalid GIF magic'):
        validators.validate_gif(path)


def test_large_gif_with_implausible_dimensions_is_rejected(tmp_path):
    # A REAL animated but too-small GIF: decode + frame count pass, dimension floor
    # rejects it.
    from PIL import Image
    path = tmp_path / 'image.gif'
    frames = [Image.new('RGB', (299, 499), c) for c in ('white', 'black')]
    frames[0].save(path, 'GIF', save_all=True, append_images=frames[1:], duration=100)
    with path.open('ab') as f:
        f.write(b'\x00' * 300_000)  # clear the size floor
    with pytest.raises(AssertionError, match='implausible GIF dimensions'):
        validators.validate_gif(path)


def test_big_png_with_valid_header_but_garbage_body_is_rejected(tmp_path):
    """2026-07 audit: a file large enough to clear the size floor, with a valid
    PNG magic + IHDR dimensions on top of garbage, passed the byte checks but does
    not decode. Full-decode validation must reject it."""
    path = tmp_path / 'image.png'
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR' + struct.pack('>II', 1200, 630)
        + b'\x00' * 200_000)  # clears the 150k size floor, but no real chunks
    with pytest.raises(AssertionError, match='does not decode'):
        validators.validate_screenshots(((path, 150_000, 1_000, 500),))


def test_big_gif_with_valid_header_but_garbage_body_is_rejected(tmp_path):
    path = tmp_path / 'image.gif'
    path.write_bytes(b'GIF89a' + struct.pack('<HH', 640, 1376) + b'\x00' * 400_000)
    with pytest.raises(AssertionError, match='does not decode|GIF has'):
        validators.validate_gif(path)


def test_single_frame_gif_is_rejected_as_not_an_animation(tmp_path):
    from PIL import Image
    path = tmp_path / 'still.gif'
    Image.new('RGB', (640, 1376), 'white').save(path, 'GIF')
    # pad past the 300k size floor so the decode/frame check is what fires
    with path.open('ab') as f:
        f.write(b'\x00' * 300_000)
    with pytest.raises(AssertionError, match='expected an animation|does not decode'):
        validators.validate_gif(path)


def test_real_multiframe_gif_and_real_png_decode_and_pass(tmp_path):
    from PIL import Image
    png = tmp_path / 'ok.png'
    Image.new('RGB', (1200, 630), 'white').save(png, 'PNG')
    with png.open('ab') as f:
        f.write(b'')  # keep it small; use a tiny size floor
    validators.validate_screenshots(((png, 100, 1000, 500),))

    gif = tmp_path / 'ok.gif'
    frames = [Image.new('RGB', (640, 1376), c) for c in ('white', 'black', 'white')]
    frames[0].save(gif, 'GIF', save_all=True, append_images=frames[1:], duration=100)
    with gif.open('ab') as f:
        f.write(b'\x00' * 300_000)  # clear the size floor
    validators.validate_gif(gif)


@pytest.mark.parametrize('exc', [EOFError, OSError, SyntaxError, ValueError])
def test_png_decode_wraps_all_pillow_failure_types(tmp_path, monkeypatch, exc):
    """2026-07 review: EOFError from a truncated PNG must become AssertionError like
    the other decode failures, not escape raw (the GIF handler already caught it).
    ValueError is expected to still escape (not a decode error) — see below."""
    from PIL import Image
    real = tmp_path / 'ok.png'
    Image.new('RGB', (1200, 630), 'white').save(real, 'PNG')

    def boom(*a, **k):
        raise exc('boom')
    monkeypatch.setattr('PIL.Image.open', boom)

    if exc is ValueError:  # not in the caught set — must not be silently swallowed
        with pytest.raises(ValueError):
            validators.validate_screenshots(((real, 100, 1000, 500),))
    else:
        with pytest.raises(AssertionError, match='PNG does not decode'):
            validators.validate_screenshots(((real, 100, 1000, 500),))


def _portfolio_with_sources(path, holdings):
    """holdings: list of (ticker, data_source). Builds a us_stocks portfolio."""
    return write_json(path, {'portfolios': {
        'us_stocks': {'holdings': [
            {'ticker': t, 'shares': 1, 'data_source': ds} for t, ds in holdings]},
        'hk_stocks': {'holdings': []}}})


def test_eod_rejects_a_held_holding_whose_quote_is_stale(tmp_path):
    """2026-07 audit #9: the archive copies portfolio.json current_price with no
    refresh, so a holding whose quote fetch broke is archived as this week's close.
    A held holding priced >5 days before the snapshot must fail, naming it."""
    snap = '2026-07-24'
    archive = write_eod(tmp_path / 'eod.csv', snap, ('CRCL', 'NVDA'))
    portfolio = _portfolio_with_sources(tmp_path / 'pf.json', [
        ('CRCL', 'Nasdaq API (stocks) Jul 23, 2026 20:01 ET'),   # fresh
        ('NVDA', 'Eastmoney realtime quote May 7, 2026 09:30 ET'),  # 2.5 months stale
    ])
    with pytest.raises(AssertionError, match=r'stale.*NVDA'):
        validators.validate_eod_archive(archive, portfolio, snapshot_date=snap)


def test_eod_accepts_fresh_quotes_including_no_year_hk_format(tmp_path):
    snap = '2026-07-25'  # Saturday archive after Fri Jul 24 close
    archive = write_eod(tmp_path / 'eod.csv', snap, ('CRCL', '00100'))
    portfolio = _portfolio_with_sources(tmp_path / 'pf.json', [
        ('CRCL', 'Nasdaq API (stocks) Jul 24, 2026 20:01 ET'),
        ('00100', 'Tencent Jul 24 16:00 HKT'),   # no year — must resolve to snapshot year
    ])
    validators.validate_eod_archive(archive, portfolio, snapshot_date=snap)


def test_eod_skips_freshness_when_data_source_is_unparseable(tmp_path):
    """Fail-safe: an unparseable data_source must never fail the archive (a parse
    miss is not evidence of staleness)."""
    snap = '2026-07-24'
    archive = write_eod(tmp_path / 'eod.csv', snap, ('CRCL',))
    portfolio = _portfolio_with_sources(tmp_path / 'pf.json', [
        ('CRCL', 'some source with no recognizable date'),
    ])
    validators.validate_eod_archive(archive, portfolio, snapshot_date=snap)


def test_eod_holiday_weekend_gap_within_window_passes(tmp_path):
    """A 3-day gap (long weekend) is within PRICE_STALE_DAYS and must pass."""
    snap = '2026-07-27'  # Monday
    archive = write_eod(tmp_path / 'eod.csv', snap, ('CRCL',))
    portfolio = _portfolio_with_sources(tmp_path / 'pf.json', [
        ('CRCL', 'Nasdaq API (stocks) Jul 24, 2026 20:01 ET'),  # 3 days
    ])
    validators.validate_eod_archive(archive, portfolio, snapshot_date=snap)


@pytest.mark.parametrize('ds,ref,expected', [
    ('Nasdaq API Jul 23, 2026 20:01 ET', '2026-07-25', '2026-07-23'),
    ('Tencent Jul 24 16:00 HKT', '2026-07-25', '2026-07-24'),
    ('quote 2026-07-17', '2026-07-25', '2026-07-17'),
    ('Tencent Jan 2 16:00 HKT', '2026-12-30', '2026-01-02'),  # no year, same year
    ('Tencent Dec 31 16:00 HKT', '2026-01-02', '2025-12-31'),  # no year → prior year
    ('no date at all', '2026-07-25', None),
])
def test_quote_date_parser(ds, ref, expected):
    from datetime import date
    got = validators._quote_date(ds, date.fromisoformat(ref))
    assert got == (date.fromisoformat(expected) if expected else None)
