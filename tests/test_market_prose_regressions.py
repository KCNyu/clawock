"""Regression cases for authored market prose and its evidence transport."""
import json
from pathlib import Path

import pytest

from clawock import prose_claims
from clawock.context.intraday_packet import PART_BYTES
from clawock.decision.packet import _event_view
from clawock.evidence.live_sources import summarize
from clawock.harness import brief_render, intraday_postflight, report, report_preflight
from clawock.prose_validation import check_pipeline_self_reference, check_storytelling


STRUCTURED = {prose_claims.FIELD: prose_claims.VERSION}
BODY = ('▎情绪面\nCRCL 随同业回落，暂未找到独立催化。\n'
        '▎技术面\n成交缩量，等收盘确认。\n'
        '▎操作建议\n按原计划持有。')


def test_model_can_never_mark_a_broken_claim_advisory(tmp_path):
    for claim in ('[[/ctx/x|(advisory)]]', '[[/ctx/(advisory)]]'):
        _, issues = report.prepare_report(STRUCTURED, BODY + claim, tmp_path)
        assert report.categorize(issues) == 'fail'
        assert any(prose_claims.ISSUE in issue for issue in issues)
    assert report.categorize(check_pipeline_self_reference('读 preflight')) == 'warn'


def test_intraday_rejects_look_and_see_but_accepts_a_short_concrete_read():
    stub = '▎我的看法\n看情况。'
    assert intraday_postflight.categorize(
        intraday_postflight.validate(stub, STRUCTURED, stub)) == 'fail'
    for prose, context in (
        ('▎我的看法\n缩量回落，等收盘确认。', STRUCTURED),
        ('▎我的看法\n本档无实质变化。', {**STRUCTURED, 'semantic_unchanged': True}),
    ):
        assert intraday_postflight.validate(prose, context, prose) == []


def test_report_checks_every_mover_inside_sentiment_and_fails_one_plan_conflict():
    ctx = {**STRUCTURED, 'anomalies': [{'ticker': 'CRCL'}, {'ticker': 'NVDA'}]}
    issues = report.validate(BODY + '\nNVDA 观察。', ctx, BODY + '\nNVDA 观察。')
    assert any('异动归因漏写' in issue and 'NVDA' in issue for issue in issues)
    assert report.categorize(issues) == 'fail'
    merged = BODY.replace('CRCL 随同业', 'CRCL 和 NVDA 随同业')
    assert not report.validate(merged, ctx, merged)
    conflict = BODY.replace('按原计划持有', 'CRCL 现在立即减仓')
    policy = {**STRUCTURED, 'holding_policies': {'CRCL': {'forbid_reduce_advice': True}}}
    assert report.categorize(report.validate(conflict, policy, conflict)) == 'fail'
    assert report.categorize(['仓位支配度不符: CRCL 同代账本与正文冲突']) == 'fail'


def test_report_rejects_shell_without_enforcing_length_or_extra_sections():
    stub = '▎情绪面\n跌\n▎技术面\n弱\n▎操作建议\n等'
    assert report.categorize(report.validate(stub, STRUCTURED, stub)) == 'fail'
    stub = BODY.replace('CRCL 随同业回落，暂未找到独立催化。', '涨。')
    assert report.categorize(report.validate(stub, STRUCTURED, stub)) == 'fail'
    assert not report.validate(BODY, STRUCTURED, BODY)
    extra = BODY + '\n▎证据\n原公告在此。'
    assert report.categorize(report.validate(extra, STRUCTURED, extra)) == 'fail'


def test_report_live_news_requires_each_name_and_prefers_current_filings(tmp_path):
    ctx = {**STRUCTURED, 'live_information': {'summary': {
        'CRCL': [{'cite': '《公司披露》（SEC，本场）', 'grade': 'primary', 'stale': False},
                 {'cite': '《同业观察》（报社，本场）', 'grade': 'soft', 'stale': False}],
        'NVDA': [{'cite': '《新订单》（SEC，提交时点未知）', 'stale': None,
                  'filed_date': '2026-11-27', 'grade': 'primary'}],
        'AMD': [{'cite': '《旧闻》（报社，上场）', 'stale': True}],
        'META': [{'cite': '《时点未核实》（报社）', 'stale': None}],
    }}}
    refs = '[[/ctx/live_information/summary/CRCL/1|cite]]'
    wrong = BODY.replace('▎技术面', refs + '\n▎技术面')
    _, issues = report.prepare_report(ctx, wrong, tmp_path)
    assert report.categorize(issues) == 'fail'
    assert any('逐票资讯漏引' in issue and 'CRCL、NVDA' in issue for issue in issues)
    right = wrong.replace('/CRCL/1|cite', '/CRCL/0|cite').replace(
        '▎技术面', 'NVDA [[/ctx/live_information/summary/NVDA/0|cite]]。\n▎技术面')
    text, issues = report.prepare_report(ctx, right, tmp_path)
    assert not issues and '公司披露' in text and '新订单' in text


@pytest.mark.parametrize('prose', [
    '这不是成交，而是计划挂单。',
    '路透报道，业内认为收购尚有变数。',
    '综上所述，继续观察。\n若回落到支撑区，复查原计划。',
    '他说“旧计划——等收盘——仍有效”。',
])
def test_storytelling_ignores_factual_contrasts_named_sources_and_quoted_dashes(prose):
    assert not check_storytelling(prose, '报告')


def test_storytelling_still_flags_unsourced_authority_and_generic_closer():
    result, = check_storytelling('业内认为会涨。\n综上所述，继续观望。', '报告')
    assert '归因没说是谁' in result and '套话收尾' in result


def test_news_headlines_and_evidence_keep_the_original_trace():
    title = '开盘前公司正式披露董事会投票结果及重组交易所需条件并继续确认下一个审批时间点'
    url = 'https://news.example/story(1)'
    headline = {'title': title, 'source': 'Example News', 'url': url, 'published': '2026-11-27'}
    data = {'sentiment': {'tickers': [{'ticker': 'CRCL', 'news_top': [
        headline, '历史标题', {'title': '<script>alert</script>', 'url': 'javascript:alert(1)'},
    ]}]}}
    rendered = brief_render.sentiment_section(data, {})
    assert f'[{title}](https://news.example/story%281%29)' in rendered
    assert 'Example News' in rendered and '2026-11-27' in rendered
    assert '历史标题' in rendered and '<script>' not in rendered and 'javascript:' not in rendered
    assert summarize({'CRCL': [headline]})['CRCL'][0]['url'] == url
    view = _event_view({'source_url': url, 'title': title, 'primary_source': 'example.news',
                        'publication_time': {'iso': '2026-11-27'}})
    assert view['source_url'] == url
    renderer = prose_claims.ClaimRenderer({}, packet={'evidence': {'events': [view]}})
    assert 'example.news，发布 2026-11-27' in renderer.render(
        '[[/packet/evidence/events/0|cite]]', '简报')


def test_mover_citation_exposes_exchange_name_and_publication_time():
    ctx = {'mover_news': {'tickers': {'CRCL': {'items': [{
        'title': '发行人公告', 'source_class': 'sec_filing', 'published_at': '2026-11-27T15:11:00+00:00',
    }]}}}}
    renderer = prose_claims.ClaimRenderer(ctx)
    text = renderer.render('[[/ctx/mover_news/tickers/CRCL/items/0|cite]]', '报告')
    assert text == '《发行人公告》（SEC 文件，发布 2026-11-27T15:11:00+00:00）'


def test_report_packet_round_trips_every_field_in_bounded_same_generation_parts(tmp_path):
    context = {'context_id': '0123456789ab', 'market': 'hk', 'phase': 'close',
               'date': '2026-11-27', 'status': 'ok',
               'news': {str(i): ['实盘公告' * 720] for i in range(7)},
               'plan_context': {'open': [{'ticker': '00700', 'shares': 300}]},
               'anomalies': [{'ticker': '00700'}],
               'live_information': {'summary': {'00700': [
                   {'cite': '《旧闻》', 'stale': True},
                   {'cite': '《新公告》', 'stale': False, 'grade': 'primary'},
               ]}}}
    audit = json.dumps(context, ensure_ascii=False)
    first = report_preflight.write_report_packet(tmp_path, context, audit)
    assert first['complete'] and len(first['parts']) > 1
    assert first['mover_tickers'] == ['[[/ctx/anomalies/0/ticker]]']
    assert first['news_cites'] == {'00700': '[[/ctx/live_information/summary/00700/1|cite]]'}
    values = {}
    for part in first['parts']:
        raw = Path(part['path']).read_bytes()
        assert 0 < part['bytes'] == len(raw) <= PART_BYTES
        chunk = json.loads(raw)
        assert (chunk['context_id'], chunk['date'], chunk['phase']) == (
            context['context_id'], context['date'], context['phase'])
        for keys, value in chunk['fields']:
            parent = values
            for key in keys[:-1]:
                parent = parent.setdefault(key, {})
            parent[keys[-1]] = value
    assert values == context
    second = report_preflight.write_report_packet(tmp_path, {
        **context, 'context_id': '0123456789ac',
    }, audit)
    assert second['prose_path'] != first['prose_path']
