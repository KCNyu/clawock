"""json_repair — what it recovers, and the far more important list of what it refuses.

The failure this exists for (2026-07-28): the daily brief wrote
`memory/.tmp/insights-2026-07-28.json` with the closing quote missing from the
last `data_caveats` entry. `json.load` raised, `build_dashboard` dropped the
behavioural-review / bear-case / concentration cards, and the daily Cron Health
Check went red — for one absent byte in 4,361.

Two earlier designs of this module were rejected for silently destroying data,
and the tests that would have caught them are the point of this file:

  * cutting to the outermost balanced value ("strip the prose") deletes a whole
    second document in `{"kept":1}\\n{"lost":2}`;
  * closing a truncated document turns "the file was cut off" into "a valid
    document with fewer items" — for a plan, decisions silently vanishing.

Both are now non-goals: those inputs must fail loudly. The suite is organised by
the property defended, not by function, because the refusals are what keep the
recoveries safe.
"""
import json
import sys
from pathlib import Path

import pytest

from clawock import json_repair  # noqa: E402
from clawock.json_repair import AMBIGUOUS, CLEAN, REPAIRED, UNREPAIRABLE  # noqa: E402


# The 2026-07-28 shape, reduced to the defect and its neighbours: a caveat whose
# closing quote is missing, with a further key after the array. The real file is
# larger; `test_the_real_production_file_recovers_whole` reads it when present.
BROKEN_INSIGHTS = '''{
  "generated_at": "2026-07-28T08:09:00+08:00",
  "behavioral_review": [
    {"tag": "bias", "text": "chased the gap"}
  ],
  "data_caveats": [
    "US data_source stamped 2026-07-27",
    "FOMC 7/29 + MSFT AMC 7/29 both land in tonight's US window
  ],
  "watchlist_for_kcn_review": ["MSFU swap"]
}
'''


def test_missing_closing_quote_recovers_every_key():
    obj, repairs, status = json_repair.repair_json(BROKEN_INSIGHTS)

    assert status == REPAIRED
    assert repairs == ['unterminated_string']
    # The key list, not just parseability: a repair that folded the following
    # lines into the broken string would also parse, and would silently eat
    # `watchlist_for_kcn_review`. Only the shape shows the difference.
    assert list(obj) == ['generated_at', 'behavioral_review', 'data_caveats',
                         'watchlist_for_kcn_review']
    assert len(obj['data_caveats']) == 2
    assert obj['data_caveats'][1].endswith("tonight's US window")
    assert obj['watchlist_for_kcn_review'] == ['MSFU swap']


# ── Refusals: the passes that were removed must stay removed ─────────────────

def test_two_balanced_documents_are_not_silently_truncated_to_one():
    """The input that killed the prose-stripping pass.

    The whole text is bracket-balanced, so matching brackets from the first `{`
    yields a document that parses — while deleting the second one. Parser
    acceptance says nothing about whether the discarded suffix was noise, so
    this must fail rather than pick.
    """
    obj, repairs, status = json_repair.repair_json(
        'model output:\n{"kept": 1}\n{"lost": 2}'
    )

    assert status == UNREPAIRABLE
    assert obj is None


@pytest.mark.parametrize('text', [
    '[[1],2',                                  # inner closer is not the document's
    '{"a": [1, 2, 3], "b": {"c": ',
    '{"decisions": [{"ticker": "PLTU"}, {"ticker": "SPCH"',
    '{"a": 1, "b":',
])
def test_a_truncated_document_fails_loudly(text):
    """Truncation means data is already gone. Closing over the loss would
    republish a shorter document as if it were whole — for a day's plan, that is
    decisions disappearing with nothing to show for it."""
    obj, repairs, status = json_repair.repair_json(text)

    assert status == UNREPAIRABLE
    assert obj is None


def test_a_comma_that_is_a_value_is_not_deleted():
    """A blanket trailing-comma regex deletes the second element here, because a
    string containing a comma sits immediately before the closer."""
    obj, repairs, status = json_repair.repair_json('["a", ","]')

    assert status == CLEAN
    assert obj == ['a', ',']


def test_a_comma_value_survives_alongside_a_real_defect():
    obj, repairs, status = json_repair.repair_json('[\n  "a\n",\n  ",\n]')

    assert status == REPAIRED
    assert obj == ['a\n', ',']


# ── Refusal: competing readings ──────────────────────────────────────────────

def test_an_ambiguous_insertion_point_is_refused_too():
    """Ambiguity inside ONE pass counts, not just between two passes.

    `{"a":"kept   \\n}` can be closed before or after the trailing spaces. Both
    parse; they disagree about whether the spaces belong to the value. Emitting
    only the trimmed candidate deleted characters from inside a string literal —
    the exact thing the module's invariant forbids — while reporting `repaired`.
    """
    obj, repairs, status = json_repair.repair_json('{"a":"kept   \n}')

    assert status == AMBIGUOUS
    assert obj is None


def test_a_line_without_trailing_space_has_only_one_insertion_point():
    """The common case must not become ambiguous just because the search widened."""
    obj, repairs, status = json_repair.repair_json('{"a": 1, "b": "tail\n}')

    assert status == REPAIRED
    assert obj == {'a': 1, 'b': 'tail'}


@pytest.mark.parametrize('text,expected', [
    ('{"path":"C:\\\\\n}', {'path': 'C:\\'}),          # even run: escape finished
    ('{"path":"C:\\\\\\\\\n}', {'path': 'C:\\\\'}),
])
def test_an_even_backslash_run_is_a_finished_escape(text, expected):
    """`endswith('\\\\')` rejected even runs as if mid-escape. Only odd parity is."""
    obj, repairs, status = json_repair.repair_json(text)

    assert status == REPAIRED
    assert obj == expected


def test_an_odd_backslash_run_still_declines():
    obj, repairs, status = json_repair.repair_json('{"path":"C:\\\n}')

    assert status == UNREPAIRABLE


@pytest.mark.parametrize('raw', ['\x00', '\x08', '\x0b', '\x0c', '\x1f', '\t', '\n', '\r'])
def test_every_c0_control_character_is_escaped(raw):
    """JSON forbids all of U+0000–U+001F raw. Handling only \\n/\\r/\\t left NUL,
    backspace, form feed and the separators reported as unrepairable."""
    obj, repairs, status = json_repair.repair_json('{"a": "x%sy"}' % raw)

    assert status == REPAIRED
    assert obj == {'a': f'x{raw}y'}


# ── Refusal: what the parser accepts but we cannot publish ───────────────────

def test_duplicate_keys_are_rejected_rather_than_collapsed():
    """`json.loads` keeps the last duplicate and drops the rest without a word.

    That is a value deletion carried out by the parser instead of by a pass, so
    it slips past every invariant the passes were written to satisfy: the input
    below would otherwise report a successful repair having thrown away `1`.
    """
    obj, repairs, status = json_repair.repair_json('{"a":1,"a":"x\n}')

    assert status == UNREPAIRABLE
    assert obj is None


@pytest.mark.parametrize('text', ['{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'])
def test_non_finite_constants_are_rejected(text):
    """Python extensions, not JSON. Accepting them writes a token no strict
    parser can read into the published dashboard payload."""
    obj, repairs, status = json_repair.repair_json(text)

    assert status == UNREPAIRABLE


def test_a_lone_surrogate_is_rejected_before_it_can_abort_the_build():
    """`"\\ud800"` parses fine, then kills `payload.encode('utf-8')` in
    build_dashboard — one malformed sidecar aborting the entire build is
    strictly worse than the missing card this module exists to prevent."""
    obj, repairs, status = json_repair.repair_json('{"status_banner": "\\ud800"}')

    assert status == UNREPAIRABLE
    assert obj is None


def test_a_valid_surrogate_pair_still_loads():
    """The rejection must not catch astral characters — kcn's sidecars carry
    emoji. By this point Python has already combined a valid pair into one
    character, so anything left in the surrogate range is genuinely unpaired."""
    obj, repairs, status = json_repair.repair_json('{"a": "\\ud83d\\ude00 ok"}')

    assert status == CLEAN
    assert obj == {'a': '😀 ok'}
    json.dumps(obj, ensure_ascii=False).encode('utf-8')   # the call that crashed


def test_competing_readings_are_refused_not_guessed():
    """A dropped quote and a raw newline are indistinguishable by scanning, and
    here both readings parse to *different* objects. Picking one would be a
    guess dressed as a repair."""
    obj, repairs, status = json_repair.repair_json('[\n "a\n,",\n "\n]')

    assert status == AMBIGUOUS
    assert obj is None
    assert 'ambiguous' in json_repair.describe(repairs, status)


def test_type_differences_count_as_disagreement():
    """`True == 1` and `1 == 1.0` in Python. If branch comparison used plain
    equality, two readings that disagree about a value's JSON type would pass as
    agreeing."""
    assert json_repair._json_equal({'a': True}, {'a': 1}) is False
    assert json_repair._json_equal({'a': 1}, {'a': 1.0}) is False
    assert json_repair._json_equal({'a': [1, {'b': None}]}, {'a': [1, {'b': None}]})


# ── Property: valid input is never touched ───────────────────────────────────

@pytest.mark.parametrize('text', [
    '{"a": [1, 2], "b": "x"}',
    '{"a": "he said \\"hi\\", then left"}',
    '{"a": "escaped\\nnewline is fine"}',
    '{"note": "use {a: 1} as the shape"}',
    '{"csv": "a,b,c"}',
    '[]', '{}', '  {"padded": true}\n\n',
    '{"unicode": "港股 25,236 ▲0.11%"}',
])
def test_valid_json_is_clean_and_unchanged(text):
    obj, repairs, status = json_repair.repair_json(text)

    assert status == CLEAN
    assert repairs == []
    assert obj == json.loads(text)


# ── Each surviving pass, on the defect it owns ───────────────────────────────

@pytest.mark.parametrize('name,text,expected', [
    ('code_fence', '```json\n{"a": 1}\n```', {'a': 1}),
    ('code_fence', '```\n{"a": 1}\n```', {'a': 1}),
    ('trailing_comma', '{"a": [1, 2,],}', {'a': [1, 2]}),
    ('trailing_comma', '[1, 2,]', [1, 2]),
    ('unterminated_string', '{\n "a": [\n  "one",\n  "two\n ]\n}',
     {'a': ['one', 'two']}),
    ('unterminated_string', '{"a": 1, "b": "tail\n}', {'a': 1, 'b': 'tail'}),
    ('control_chars_in_string', '{"a": "line1\nline2"}', {'a': 'line1\nline2'}),
    ('control_chars_in_string', '{"a": "col1\tcol2"}', {'a': 'col1\tcol2'}),
])
def test_single_defect_is_repaired_and_named(name, text, expected):
    obj, repairs, status = json_repair.repair_json(text)

    assert status == REPAIRED
    assert obj == expected
    assert repairs == [name]


def test_passes_compose_when_a_file_carries_two_defects():
    obj, repairs, status = json_repair.repair_json('```json\n{"a": [1, 2,],}\n```')

    assert status == REPAIRED
    assert obj == {'a': [1, 2]}
    assert repairs == ['code_fence', 'trailing_comma']


def test_a_genuine_multiline_value_keeps_the_multiline_reading():
    """The mirror of the 07-28 case: closing the string at the break leaves
    `line2", "b": 2}` dangling, so that branch never parses and only the
    escaping reading survives."""
    obj, repairs, status = json_repair.repair_json('{"a": "line1\nline2", "b": 2}')

    assert status == REPAIRED
    assert obj == {'a': 'line1\nline2', 'b': 2}
    assert repairs == ['control_chars_in_string']


# ── Beyond repair ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('text', ['not json at all', '', '   ', 'null and then some'])
def test_beyond_repair_claims_nothing(text):
    obj, repairs, status = json_repair.repair_json(text)

    assert status == UNREPAIRABLE
    assert obj is None
    # A repair list on a failed parse would misreport what happened.
    assert repairs == []


def test_non_string_input_is_rejected_rather_than_coerced():
    assert json_repair.repair_json(None) == (None, [], UNREPAIRABLE)
    assert json_repair.repair_json(b'{"a": 1}') == (None, [], UNREPAIRABLE)


# ── File helper ──────────────────────────────────────────────────────────────

def test_load_json_repaired_reads_and_reports(tmp_path):
    p = tmp_path / 'insights-2026-07-28.json'
    p.write_text(BROKEN_INSIGHTS, encoding='utf-8')

    obj, repairs, status = json_repair.load_json_repaired(p)

    assert status == REPAIRED
    assert obj['generated_at'].startswith('2026-07-28')
    assert repairs == ['unterminated_string']


def test_a_missing_file_still_raises():
    """Absence is not a syntax defect; swallowing it would hide a producer that
    stopped writing at all behind a 'repaired' label."""
    with pytest.raises(OSError):
        json_repair.load_json_repaired('/nonexistent/insights.json')


def test_describe_is_empty_for_clean_input():
    assert json_repair.describe([], CLEAN) == ''
    assert 'unterminated_string' in json_repair.describe(['unterminated_string'])


FIXTURE = Path(__file__).parent / 'fixtures' / 'insights-unterminated-quote.json'


def test_the_full_production_shape_recovers_whole():
    """The inline fixture above is reduced to the defect and its neighbours; this
    is the whole 2026-07-28 document — all eight keys, the real nesting, the
    defect in its original position — with every narrative string and every
    number replaced by placeholders, because this repository is public and the
    sidecar carries kcn's portfolio commentary. `generated_at` and `date` are
    kept as schema-shaped literals so the document still looks like what the
    brief writes. Verified to produce the same status, the same pass list and the
    same key count as the file that actually broke."""
    obj, repairs, status = json_repair.load_json_repaired(FIXTURE)

    assert status == REPAIRED
    assert repairs == ['unterminated_string']
    assert list(obj) == ['generated_at', 'date', 'behavioral_review', 'bear_cases',
                         'hidden_concentration', 'thesis_uncertainty',
                         'data_caveats', 'watchlist_for_kcn_review']
    # The key after the broken array is the one a folding repair would eat.
    assert obj['watchlist_for_kcn_review']


def test_the_fixture_keeps_the_defect_where_it_really_was():
    """The defect must sit in `data_caveats`, with a sibling key still after it.

    An earlier fixture moved it to the final key, which quietly removed the very
    shape the test above exists to defend — with nothing following the defect,
    a repair that swallows the rest of the document looks identical to a correct
    one.
    """
    raw = FIXTURE.read_text(encoding='utf-8')
    # Locate the defect the way the repairer does. Counting raw quotes per line
    # is unsound: a valid string holding one escaped quote also has an odd count,
    # so that heuristic can point at a healthy line and pass while the real
    # defect sits somewhere else entirely.
    start = next(s for s, end in json_repair._iter_string_spans(raw)
                 if end is None or '\n' in raw[s:end])
    lines = raw.split('\n')
    defect = raw[:start].count('\n')

    assert any('"data_caveats"' in line for line in lines[:defect])
    assert any('"watchlist_for_kcn_review"' in line for line in lines[defect:])
