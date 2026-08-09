import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from scripts.data import gh_action_news_digest
from clawock.evidence import news_evidence_graph as graph
from clawock.publish import artifacts as validate_sidecars
from clawock_kcnyu.harness import brief_postflight


POLICY = graph.load_policy()
NOW = datetime(2026, 7, 26, 8, tzinfo=timezone.utc)


def _event(title='ABC faces SEC investigation', **overrides):
    values = {
        'ticker': 'ABC',
        'title': title,
        'published_at': NOW.isoformat(),
        'event_time': NOW.isoformat(),
        'origin': 'sec_filing',
        'source': 'SEC EDGAR',
        'url': 'https://www.sec.gov/Archives/abc.htm',
        'event_type': 'filing_8k',
    }
    values.update(overrides)
    return graph.make_event(POLICY, **values)


def _confirmed(events, *, price_change=-3.0, peer=None):
    portfolio = {
        'portfolios': {
            'us_stocks': {
                'holdings': [{
                    'ticker': 'ABC',
                    'shares': 1,
                    'today_change_pct': price_change,
                }],
            },
            'hk_stocks': {'holdings': []},
        },
    }
    graph.apply_novelty(POLICY, events, [], NOW)
    graph.apply_expiry(POLICY, events, NOW)
    graph.apply_confirmation(
        POLICY,
        events,
        portfolio,
        peer or {},
        {},
    )
    return graph.gate_events(POLICY, events)


def test_normalize_timestamp_and_event_id_include_event_time():
    timestamp = graph.normalize_timestamp('Sun, 26 Jul 2026 08:30:00 GMT')
    assert timestamp == {
        'iso': '2026-07-26T08:30:00+00:00',
        'precision': 'minute',
    }

    first = _event(event_time='2026-07-26T08:00:00+00:00')
    second = _event(event_time='2026-07-26T09:00:00+00:00')
    assert first['novelty_cluster'] == second['novelty_cluster']
    assert first['event_id'] != second['event_id']


def test_source_type_rejects_sec_domain_substring_spoofing():
    assert graph.source_type(
        origin='gnews-rss',
        source='Untrusted',
        url='https://sec.gov.attacker.example/story',
    ) == 'google_news_rss'
    assert graph.source_type(
        origin='gnews-rss',
        source='SEC mirror',
        url='https://www.sec.gov/Archives/abc.htm',
    ) == 'sec_filing'


def test_deduplicate_prefers_primary_source_and_keeps_corroboration():
    weak = _event(
        origin='gnews-rss',
        source='Example News',
        url='https://example.com/story',
    )
    strong = _event()
    result = graph.deduplicate_events([weak, strong])

    assert len(result) == 1
    assert result[0]['source_type'] == 'sec_filing'
    assert result[0]['duplicate_event_ids'] == [weak['event_id']]
    assert result[0]['corroborating_source_count'] == 2


def test_deduplicate_collapses_paraphrased_event_summaries():
    first = _event(
        title=(
            'SpaceX Starship 今夜测试，同时让出 Falcon 客户，'
            '测试失败构成执行风险'
        ),
        ticker='SPCX',
        origin='llm_digest_legacy',
        source='legacy digest',
        url='',
        event_type='product',
    )
    second = _event(
        title=(
            'Starship 今夜重大测试若失败，Falcon 客户迁移会放大'
            ' SpaceX 执行风险'
        ),
        ticker='SPCX',
        origin='gnews-rss',
        source='Example News',
        url='https://example.com/starship',
        event_type='product',
    )
    result = graph.deduplicate_events([first, second])

    assert len(result) == 1
    assert len(result[0]['duplicate_event_ids']) == 1
    assert result[0]['duplicate_novelty_clusters']


def test_hkex_headline_is_prioritized_as_exchange_announcement():
    event = _event(
        ticker='00100',
        title='MINIMAX GROUP INC. - W issuer announcement',
        origin='gnews-rss',
        source='hkex.com.hk',
        url='https://news.google.com/rss/articles/example',
        event_type='financing',
    )

    assert event['source_type'] == 'exchange_announcement'
    assert event['source_reliability'] == 0.97


def test_generic_hkex_listing_page_is_not_treated_as_announcement():
    event = _event(
        ticker='03032',
        title='Company Name + Stock Code - price, quote, history',
        origin='gnews-rss',
        source='hkex.com.hk',
        url='https://news.google.com/rss/articles/example',
        event_type='other',
    )

    assert event['source_type'] == 'google_news_rss'
    assert event['source_reliability'] == 0.5


def test_repeated_cluster_loses_novelty_and_expired_event_cannot_escalate():
    event = _event()
    history = [{
        'as_of': '2026-07-25',
        'events': [{
            'event_id': 'older-id',
            'ticker': 'ABC',
            'novelty_cluster': event['novelty_cluster'],
            'published_at': (NOW - timedelta(days=1)).isoformat(),
        }],
    }]
    graph.apply_novelty(POLICY, [event], history, NOW)
    assert event['novelty_score'] == 0.1
    assert event['novelty_reason'] == 'same_cluster_within_2d'

    old = _event(published_at=(NOW - timedelta(days=9)).isoformat())
    _confirmed([old])
    assert old['status'] == 'expired'
    assert old['actionable_escalation'] is False
    assert 'not_expired' in old['actionable_blockers']


def test_primary_source_resolution_restores_novelty():
    event = _event()
    history = [{
        'as_of': '2026-07-25',
        'events': [{
            'event_id': 'weak-rumor',
            'ticker': 'ABC',
            'novelty_cluster': event['novelty_cluster'],
            'event_type': event['event_type'],
            'title': event['title'],
            'source_type': 'google_news_rss',
            'source_reliability': 0.5,
            'published_at': (NOW - timedelta(days=1)).isoformat(),
        }],
    }]
    graph.apply_novelty(POLICY, [event], history, NOW)

    assert event['novelty_score'] == 1.0
    assert event['novelty_reason'] == 'primary_source_resolution'


def test_only_confirmed_negative_primary_event_can_escalate():
    negative = _event()
    positive = _event(
        title='ABC receives approval and raises guidance',
        published_at=(NOW + timedelta(minutes=1)).isoformat(),
    )
    _confirmed([negative, positive])

    assert negative['confirmation']['price_aligned'] is True
    assert negative['actionable_escalation'] is True
    assert positive['impact_direction'] == 'positive'
    assert positive['actionable_escalation'] is False
    assert 'disconfirming_negative' in positive['actionable_blockers']


def test_uncalibrated_peer_observation_is_not_confirmation():
    event = _event()
    peer = {
        'live': {
            'ABC': {
                'residual_blend_1d': -2.0,
                'peer_dispersion_1d': 1.0,
                'triggered_rules': ['laggard_avoidance'],
            },
        },
        'rule_activation': {
            'laggard_avoidance': {'usable_for_decisions': False},
        },
    }
    _confirmed([event], price_change=None, peer=peer)

    confirmation = event['confirmation']
    assert confirmation['peer_residual_observed'] is True
    assert confirmation['peer_confirmation_usable'] is False
    assert confirmation['confirmed'] is False
    assert event['actionable_escalation'] is False


def test_leveraged_product_volume_is_not_compared_with_underlying_liquidity():
    event = _event(
        ticker='PLTR',
        reported_ticker='PLTU',
    )
    portfolio = {
        'portfolios': {
            'us_stocks': {
                'holdings': [{
                    'ticker': 'PLTU',
                    'shares': 1,
                    'today_change_pct': -3.0,
                    'volume': 1_000_000,
                    'current_price': 25.0,
                }],
            },
            'hk_stocks': {'holdings': []},
        },
    }
    graph.apply_confirmation(
        POLICY,
        [event],
        portfolio,
        {},
        {'live_rankings': {'PLTR': {'liquidity': 10_000_000}}},
    )

    assert event['confirmation']['price_aligned'] is True
    assert event['confirmation']['volume_ratio_vs_20d_median'] is None


def test_tavily_queue_is_only_unresolved_high_impact():
    high = _event(
        title='ABC regulatory proceeding update',
        origin='gnews-rss',
        source='Example News',
        url='https://example.com/regulatory',
        event_type='regulatory',
    )
    low = _event(
        title='ABC shares discussed by investors',
        published_at=(NOW + timedelta(minutes=1)).isoformat(),
        origin='gnews-rss',
        source='Example News',
        url='https://example.com/chatter',
        event_type='other',
    )
    _confirmed([high, low], price_change=0.0)
    queue = graph.tavily_queue(POLICY, [high, low])

    assert [row['event_id'] for row in queue] == [high['event_id']]
    assert queue[0]['allowed_tool'] == 'tavily-search'


def test_etf_marketing_headline_cannot_enter_tavily_queue():
    event = _event(
        ticker='SKHY',
        title='STARTRADER Launches SKHY ETF as US Market Debut',
        origin='gnews-rss',
        source='Example News',
        url='https://example.com/marketing',
        event_type='product',
    )
    _confirmed([event], price_change=0.0)

    assert event['high_impact'] is False
    assert graph.tavily_queue(POLICY, [event]) == []


def test_news_digest_persists_headline_metadata_not_body(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = {
        'ABC': [{
            'headline': 'ABC filing update',
            'summary': 'licensed article body must not be persisted',
            'datetime': 1785052800,
            'source': 'Wire',
            'origin': 'finnhub',
            'url': 'https://example.com/update',
        }],
    }
    gh_action_news_digest._write_artifact(
        ['ABC'],
        raw,
        {'ABC': {'finnhub': 'success'}},
        digest='short derived digest',
    )
    payload = json.loads(
        (tmp_path / 'assets/data/us_news_digest.json').read_text()
    )

    assert payload['raw_news_evidence']['ABC'][0] == {
        'headline': 'ABC filing update',
        'datetime': 1785052800,
        'source': 'Wire',
        'origin': 'finnhub',
        'url': 'https://example.com/update',
    }
    assert 'summary' not in payload['raw_news_evidence']['ABC'][0]


def test_news_digest_validator_rejects_licensed_body_fields(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = {
        'ABC': [{
            'headline': 'ABC filing update',
            'summary': 'not persisted',
            'datetime': int(NOW.timestamp()),
            'source': 'Wire',
            'origin': 'finnhub',
            'url': 'https://example.com/update',
        }],
    }
    gh_action_news_digest._write_artifact(
        ['ABC'],
        raw,
        {'ABC': {'finnhub': 'success'}},
        digest='## Signals\n- ABC: ' + ('material update ' * 10),
    )
    path = tmp_path / 'assets/data/us_news_digest.json'
    payload = json.loads(path.read_text())
    payload['raw_news_evidence']['ABC'][0]['summary'] = 'licensed body'
    path.write_text(json.dumps(payload))

    try:
        validate_sidecars.validate_news_digest(
            path,
            now=datetime.fromisoformat(payload['generated_at']).replace(
                tzinfo=timezone.utc
            ),
        )
    except AssertionError as exc:
        assert 'must not persist article summaries/bodies' in str(exc)
    else:
        raise AssertionError('validator accepted a persisted article summary')


def _plan(event_id):
    return {
        'schema_version': 2,
        'date': '2026-07-26',
        'decisions': [{
            'schema_version': 2,
            'decision_id': 'dec-test',
            'episode_id': 'ep-test',
            'plan_date': '2026-07-26',
            'created_at': '2026-07-26T08:00:00+08:00',
            'ticker': 'ABC',
            'strategy_id': 'event_trade',
            'action': 'cut',
            'condition': {'type': 'event', 'price': None},
            'size': {'shares': 1},
            'confidence': 0.8,
            'driven_by': 'catalyst',
            'evidence_event_id': event_id,
            'override': {'status': 'none'},
        }],
    }


def test_postflight_requires_matching_actionable_event_id(tmp_path):
    event = _event()
    _confirmed([event])
    context = {'news_evidence_graph': {'events': [event]}}
    path = tmp_path / '2026-07-26-plan.json'

    path.write_text(json.dumps(_plan(event['event_id'])))
    accepted = brief_postflight.validate_plan_json(path, context)
    assert not any('news-evidence-gate' in issue for issue in accepted)

    missing = deepcopy(_plan(None))
    path.write_text(json.dumps(missing))
    rejected = brief_postflight.validate_plan_json(path, context)
    assert any('news-evidence-gate' in issue for issue in rejected)


def test_stock_connect_membership_gets_a_type_and_a_direction():
    """港股通 membership changes were classified `other` / `unknown` (#346).

    `unknown` is not a harmless default: `apply_confirmation` derives
    `expected_sign` from the direction, so an unknown-direction event has
    `price_aligned is False` no matter how it traded. MiniMax's 2026-08-06
    inclusion was recorded as "not confirmed" on a day it moved +10.25% — which
    reads identically to a catalyst the tape rejected, when in truth the tape was
    never consulted. Escalation is asserted here too: it must stay False, because
    positive events are hold-only by design (see the sibling escalation test) and
    the fix must not smuggle in a policy change.
    """
    inclusion = '上交所：港股通标的名单调入MINIMAX-W、立讯精密、三环集团'
    removal = '港股通标的名单调出某某股份'
    assert graph.classify_event(inclusion) == 'index_inclusion'
    assert graph.classify_impact(inclusion) == 'positive'
    assert graph.classify_impact(removal) == 'negative'
    # Broad words must not fire on an unrelated negative headline.
    assert graph.classify_impact('某公司纳入调查') == 'conflicting'

    event = {
        'title': inclusion, 'ticker': '00100', 'reported_ticker': '00100',
        'event_type': graph.classify_event(inclusion),
        'impact_direction': graph.classify_impact(inclusion),
        'source_reliability': 0.62, 'novelty_score': 1.0, 'status': 'active',
    }
    portfolio = {'portfolios': {'hk_stocks': {'holdings': [
        {'ticker': '00100', 'today_change_pct': 10.25,
         'current_price': 253.8, 'volume': 38060, 'shares': 120}]}}}
    graph.apply_confirmation(POLICY, [event], portfolio, {}, {})
    graph.gate_events(POLICY, [event])
    assert event['confirmation']['price_aligned'] is True
    assert event['actionable_escalation'] is False
