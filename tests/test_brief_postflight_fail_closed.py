"""brief_postflight must fail closed when the preflight context is unusable.

Regression for the silent-green path: a missing or unparseable
memory/.tmp/brief-context-{today}.json used to leave ``context=None``, which
skipped every context-dependent hard gate (generation pin, position/leverage
回查, peer divergence, macro/sentiment) while the ledger recorded success.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from clawock.harness import brief_postflight  # noqa: E402
from clawock.harness.validation import categorize_issues  # noqa: E402


def test_missing_context_yields_a_critical_issue(tmp_path):
    context, issue = brief_postflight.load_preflight_context(
        tmp_path / 'brief-context-2026-08-25.json'
    )

    assert context is None
    assert issue and '缺失' in issue
    status = categorize_issues([issue], brief_postflight.CRITICAL_KEYWORDS, warn_max=4)
    assert status == 'fail'


def test_unparseable_context_yields_a_critical_issue(tmp_path):
    ctx = tmp_path / 'brief-context-2026-08-25.json'
    ctx.write_text('{"generation_id": "truncated"', encoding='utf-8')

    context, issue = brief_postflight.load_preflight_context(ctx)

    assert context is None
    assert issue and '解析失败' in issue
    status = categorize_issues([issue], brief_postflight.CRITICAL_KEYWORDS, warn_max=4)
    assert status == 'fail'


def test_readable_context_still_loads_without_an_issue(tmp_path):
    ctx = tmp_path / 'brief-context-2026-08-25.json'
    ctx.write_text('{"generation_id": "abc123"}', encoding='utf-8')

    context, issue = brief_postflight.load_preflight_context(ctx)

    assert context == {'generation_id': 'abc123'}
    assert issue is None
