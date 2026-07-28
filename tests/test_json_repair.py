"""json_repair — recovery of LLM-authored JSON, and the limits of that recovery.

The failure this exists for (2026-07-28): the daily brief wrote
`memory/.tmp/insights-2026-07-28.json` with the closing quote missing from the
last `data_caveats` entry. `json.load` raised, build_dashboard dropped the
behavioural-review / bear-case / concentration cards, and the daily Cron Health
Check went red — for one absent byte.

Tests are grouped by the property they defend, because two of them matter more
than any single repair case:
  * valid JSON is returned byte-identical, with zero repairs reported;
  * a repair never invents a value, and never silently changes the *shape* of
    the document (the unterminated-vs-multiline ambiguity below).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts' / 'data'))
import json_repair  # noqa: E402


# ── The production failure, verbatim ──────────────────────────────────────────

BROKEN_INSIGHTS = '''{
  "generated_at": "2026-07-28T08:09:00+08:00",
  "date": "2026-07-28",
  "behavioral_review": [
    {"tag": "bias", "text": "\\u8ffd\\u9ad8"}
  ],
  "data_caveats": [
    "US 7 \\u4e2a\\u6301\\u4ed3 data_source \\u6807 2026-07-27",
    "FOMC 7/29 + MSFT AMC 7/29 \\u90fd\\u5728\\u4eca\\u665a\\u7f8e\\u80a1\\u7a97\\u53e3
  ],
  "watchlist_for_kcn_review": [
    "MSFU swap"
  ]
}
'''


def test_missing_closing_quote_recovers_every_key():
    """The 07-28 shape: the repair must not eat the key that follows."""
    obj, repairs = json_repair.repair_json(BROKEN_INSIGHTS)

    assert repairs == ['unterminated_string']
    # Pinning the whole key list, not just the caveat: any repair that recovers
    # the file by folding following lines into the broken string would still
    # produce a parseable object, and only the shape shows it went wrong.
    assert list(obj) == ['generated_at', 'date', 'behavioral_review',
                         'data_caveats', 'watchlist_for_kcn_review']
    assert len(obj['data_caveats']) == 2
    assert obj['data_caveats'][1].endswith('窗口')
    assert obj['watchlist_for_kcn_review'] == ['MSFU swap']


# ── Property: valid input is never touched ────────────────────────────────────

@pytest.mark.parametrize('text', [
    '{"a": [1, 2], "b": "x"}',
    '{"a": "he said \\"hi\\", then left"}',
    '{"a": "escaped\\nnewline is fine"}',
    '[]',
    '{}',
    '  {"padded": true}\n\n',
    '{"unicode": "港股 25,236 ▲0.11%"}',
])
def test_valid_json_reports_no_repairs(text):
    obj, repairs = json_repair.repair_json(text)
    assert repairs == []
    assert obj == json.loads(text)


def test_a_string_containing_braces_is_not_treated_as_prose():
    """`_strip_prose_wrapper` must not cut inside a string value."""
    text = '{"note": "use {a: 1} as the shape"}'
    obj, repairs = json_repair.repair_json(text)
    assert repairs == []
    assert obj['note'] == 'use {a: 1} as the shape'


# ── Each repair pass, on the defect it owns ───────────────────────────────────

@pytest.mark.parametrize('name,text,expected', [
    ('code_fence', '```json\n{"a": 1}\n```', {'a': 1}),
    ('code_fence', '```\n{"a": 1}\n```', {'a': 1}),
    ('prose_wrapper', 'Sure, here it is:\n{"a": 1}\nlet me know', {'a': 1}),
    ('trailing_comma', '{"a": [1, 2,],}', {'a': [1, 2]}),
    ('unterminated_string', '{\n "a": [\n  "one",\n  "two\n ]\n}',
     {'a': ['one', 'two']}),
    ('control_chars_in_string', '{"a": "line1\nline2"}', {'a': 'line1\nline2'}),
    ('truncated_document', '{"a": [1, 2, 3], "b": {"c": ', {'a': [1, 2, 3], 'b': {}}),
    ('truncated_document', '{"a": ["x", "y",', {'a': ['x', 'y']}),
    ('truncated_document', '{"a": 1, "b":', {'a': 1}),
])
def test_single_defect_is_repaired_and_named(name, text, expected):
    obj, repairs = json_repair.repair_json(text)
    assert obj == expected
    assert repairs == [name]


def test_passes_compose_when_a_file_carries_two_defects():
    obj, repairs = json_repair.repair_json('```json\n{"a": [1, 2\n```')
    assert obj == {'a': [1, 2]}
    assert repairs == ['code_fence', 'truncated_document']


def test_multiline_value_keeps_the_multiline_reading():
    """The mirror of the 07-28 case: here the newline really is inside the value.

    Closing the string at the line break would leave `line2", "b": 2}` dangling,
    so that branch does not parse and the driver backs out of it. This is the
    property the whole design rests on — the parser picks the reading, the pass
    order is only a tiebreak — so it is asserted directly rather than inferred
    from the ordering of `_PASSES`.
    """
    obj, repairs = json_repair.repair_json('{"a": "line1\nline2", "b": 2}')
    assert obj == {'a': 'line1\nline2', 'b': 2}
    assert repairs == ['control_chars_in_string']

    # Same driver, opposite verdict, on the same class of defect.
    obj, repairs = json_repair.repair_json('{"a": "line1\n, "b": 2}')
    assert obj == {'a': 'line1', 'b': 2}
    assert repairs == ['unterminated_string']


# ── Property: unrepairable stays unrepairable ─────────────────────────────────

@pytest.mark.parametrize('text', [
    'not json at all',
    '',
    '   ',
    'null and then some',
    '{"a": 1} {"b": 2}',   # two documents — no single object to recover
])
def test_beyond_repair_returns_none_and_claims_nothing(text):
    obj, repairs = json_repair.repair_json(text)
    assert obj is None
    # A repair list on a failed parse would misreport what happened: nothing was
    # recovered, so nothing may be claimed.
    assert repairs == []


def test_non_string_input_is_rejected_rather_than_coerced():
    assert json_repair.repair_json(None) == (None, [])
    assert json_repair.repair_json(b'{"a": 1}') == (None, [])


# ── File helper + reporting ───────────────────────────────────────────────────

def test_load_json_repaired_reads_and_reports(tmp_path):
    p = tmp_path / 'insights-2026-07-28.json'
    p.write_text(BROKEN_INSIGHTS, encoding='utf-8')
    obj, repairs = json_repair.load_json_repaired(p)
    assert obj['date'] == '2026-07-28'
    assert repairs == ['unterminated_string']


def test_a_missing_file_still_raises():
    """Absence is not a syntax defect; swallowing it here would hide a producer
    that stopped writing at all behind a 'repaired' label."""
    with pytest.raises(OSError):
        json_repair.load_json_repaired('/nonexistent/insights.json')


def test_describe_is_empty_for_clean_input():
    assert json_repair.describe([]) == ''
    assert 'unterminated_string' in json_repair.describe(['unterminated_string'])
