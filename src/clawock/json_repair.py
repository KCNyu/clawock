"""
json_repair.py — bounded, lossless recovery for hand-authored JSON sidecars.

Every JSON file an agent writes by hand is one unescaped newline away from being
unreadable. On 2026-07-28 the brief dropped the closing quote on the last
`data_caveats` entry of `memory/.tmp/insights-2026-07-28.json`; `json.load`
raised `Invalid control character at line 48`; `build_dashboard` fell through to
its absent-source path and **republished the previous day's** behavioural-review
cards, and the daily health check went red — for one absent byte in 4,361.

## The invariant, stated so it can be tested

A pass may only:

  * **insert** a delimiter the author owed (a closing quote), or
  * **escape**, in place, a character that JSON forbids raw inside a string, or
  * **delete** a character that is outside every string literal and carries no
    value (a fence line, a comma before a closer).

No pass may delete a character that is inside a string literal, and no pass may
delete a *value*. This rules out two tempting repairs that earlier versions of
this module shipped, both of which silently destroyed data:

  * **prose stripping** — cutting to the outermost balanced value looks lossless
    but is not: `{"kept": 1}\\n{"lost": 2}` is balanced, and cutting to the first
    match deletes the second document. Bracket-matching only moves where the
    deletion ends; it cannot prove the discarded suffix was noise.
  * **closing a truncated document** — the tail is already gone; appending `]}`
    converts "this file was cut off" into "a valid document with fewer items".
    For a plan that is decisions silently disappearing. Truncation must fail
    loudly, so it is not repaired here.

## Ambiguity is refused, not guessed

A missing quote and a raw newline inside a string are indistinguishable by
scanning: a dropped quote mispairs every quote after it, so the opener on the
broken line pairs with the next line's opener. Both readings can parse and yield
*different objects*, and no amount of parser agreement establishes which one the
author meant. So every accepting branch is enumerated; if two of them disagree,
the result is `ambiguous` and no object is returned. Parser acceptance proves
syntax, never intent.

## Nothing is repaired silently

`repair_json` returns a status alongside the object. `clean` is the only status a
caller may treat as unremarkable — a file needing repair every day is a producer
bug, and a silent fixer would hide it forever (shared memory:
`feedback-detect-but-never-silence`).
"""
import bisect
import json
import re

# A file can carry more than one defect, so passes compose — but only to this
# depth, and only through branches the parser accepts. A pass may offer more than
# one candidate, so the bound is depth × passes × candidates-per-pass rather than
# a flat 4·3·2; `seen` keeps repeated texts from being re-explored.
_MAX_DEPTH = 3

CLEAN = 'clean'
REPAIRED = 'repaired'
AMBIGUOUS = 'ambiguous'
UNREPAIRABLE = 'unrepairable'


class _Rejected(ValueError):
    """Parsed as JSON, but carries something no consumer of ours can accept."""


def _no_duplicate_keys(pairs):
    """`json.loads` keeps the last of duplicate keys and drops the rest silently.

    That is a value deletion performed by the parser rather than by a pass, so it
    slips past the invariant every pass is written to satisfy: `{"a":1,"a":"x"}`
    would be reported as a successful repair having thrown away `1`.
    """
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise _Rejected(f'duplicate key {key!r}')
        seen.add(key)
    return dict(pairs)


def _no_non_finite(token):
    """`NaN`/`Infinity` are Python extensions, not JSON. Accepting them puts a
    token no strict parser can read into the published dashboard payload."""
    raise _Rejected(f'non-finite constant {token}')


def _reject_lone_surrogates(value):
    """A lone surrogate parses fine and then kills `payload.encode('utf-8')`.

    `build_dashboard` encodes the finished payload, so one malformed sidecar
    could abort the entire build — a strictly worse outcome than the missing
    card this module exists to prevent. Valid surrogate *pairs* are untouched:
    Python has already combined them into one astral character by this point, so
    anything still in the surrogate range is unpaired.
    """
    if isinstance(value, str):
        if any('\ud800' <= ch <= '\udfff' for ch in value):
            raise _Rejected('lone surrogate')
    elif isinstance(value, dict):
        for k, v in value.items():
            _reject_lone_surrogates(k)
            _reject_lone_surrogates(v)
    elif isinstance(value, list):
        for v in value:
            _reject_lone_surrogates(v)
    return value


def _strict_loads(text):
    """`json.loads` plus the three things it accepts that we cannot publish."""
    return _reject_lone_surrogates(json.loads(
        text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_non_finite,
    ))

_FENCE_RE = re.compile(r'^\s*```(?:json|JSON)?\s*\n(.*?)\n?\s*```\s*$', re.DOTALL)


def _iter_string_spans(text):
    """Yield (open_quote_index, close_quote_index_or_None) for every JSON string.

    Walks the raw text tracking escapes so a `\\"` inside a string does not read
    as a terminator. A trailing None close means the last string was never
    closed.
    """
    i, n = 0, len(text)
    while i < n:
        if text[i] != '"':
            i += 1
            continue
        j = i + 1
        while j < n:
            c = text[j]
            if c == '\\':
                j += 2
                continue
            if c == '"':
                break
            j += 1
        if j >= n:
            yield i, None
            return
        yield i, j
        i = j + 1


def _outside_string(text):
    """Predicate: is this index outside every string literal (quotes included)?

    Returns a callable over sorted spans rather than a materialised index set —
    the set cost O(len(text)) memory and dominated the runtime on large inputs.
    """
    starts, stops = [], []
    for start, end in _iter_string_spans(text):
        starts.append(start)
        stops.append(len(text) if end is None else end + 1)

    def outside(i):
        pos = bisect.bisect_right(starts, i) - 1
        return pos < 0 or i >= stops[pos]

    return outside


def _strip_code_fence(text):
    """```json … ``` → the payload. Deletes only the fence lines themselves."""
    m = _FENCE_RE.match(text)
    return m.group(1) if m else None


def _close_unterminated_string(text):
    """Insert the closing quote the author owed. → every plausible position.

    Handles both a span that never closes and a span that swallowed a newline —
    the two shapes a missing quote produces. Nothing is deleted; only the
    delimiter is supplied.

    Where the line has trailing whitespace the position is *itself* ambiguous:
    `{"a":"kept   \\n}` can close before or after the spaces, both parse, and the
    two disagree about whether the spaces are in the value. Returning only the
    trimmed candidate silently deleted characters from inside a string — exactly
    what this module forbids. Both are returned so the caller sees the
    disagreement and refuses.

    Declines on an *odd* run of trailing backslashes, where the author was still
    mid-escape. An even run is a finished escaped backslash and is fine.
    """
    for start, end in _iter_string_spans(text):
        if end is not None and '\n' not in text[start:end]:
            continue
        nl = text.find('\n', start + 1)
        tail = text[start:] if nl == -1 else text[start:nl]
        trimmed = tail.rstrip()
        if (len(trimmed) - len(trimmed.rstrip('\\'))) % 2:
            return None
        cuts = {start + len(trimmed), start + len(tail)}
        return [text[:c] + '"' + text[c:] for c in sorted(cuts)]
    return None


_SHORT_ESCAPE = {'\n': '\\n', '\r': '\\r', '\t': '\\t',
                 '\b': '\\b', '\f': '\\f'}


def _escape_control_chars(text):
    """Escape every raw U+0000–U+001F that sits inside a string literal.

    In place and value-preserving: the character survives as its JSON escape.
    Only characters strictly inside a closed span are touched, so the newlines
    that format the document are untouched.

    All of C0 is covered, not just the three that are easy to picture: JSON
    forbids the whole range raw, so handling `\\n`/`\\r`/`\\t` alone left NUL,
    backspace, form feed and the separators reported as unrepairable while the
    module claimed to escape "a character JSON forbids raw inside a string".
    """
    out, last, changed = [], 0, False
    for start, end in _iter_string_spans(text):
        if end is None:
            break
        body = text[start:end + 1]
        if any(ch < ' ' for ch in body):
            body = ''.join(
                _SHORT_ESCAPE.get(ch, f'\\u{ord(ch):04x}') if ch < ' ' else ch
                for ch in body
            )
            changed = True
        out.append(text[last:start])
        out.append(body)
        last = end + 1
    if not changed:
        return None
    out.append(text[last:])
    return ''.join(out)


def _drop_trailing_comma(text):
    """`[1, 2, ]` → `[1, 2]`, for commas that are outside every string.

    String-aware by construction. A blanket regex deletes the comma in
    `[\"a\", \",\"]`-shaped input — where the comma is a string's *value*, not a
    separator — which is a value deletion, not an artefact removal.
    """
    outside = _outside_string(text)
    drop = set()
    for i, ch in enumerate(text):
        if ch != ',' or not outside(i):
            continue
        j = i + 1
        while j < len(text) and text[j] in ' \t\r\n':
            j += 1
        if j < len(text) and text[j] in ']}' and outside(j):
            drop.add(i)
    if not drop:
        return None
    return ''.join(c for i, c in enumerate(text) if i not in drop)


# Tried in this order, but order is only a tiebreak: correctness comes from
# enumerating every accepting branch and refusing disagreement, not from
# guessing well.
_PASSES = (
    ('code_fence', _strip_code_fence),
    ('trailing_comma', _drop_trailing_comma),
    ('unterminated_string', _close_unterminated_string),
    ('control_chars_in_string', _escape_control_chars),
)


def _json_equal(a, b):
    """Type-sensitive structural equality.

    Plain `==` calls `True == 1` and `1 == 1.0` equal, which would let two
    branches that disagree about a value's JSON *type* pass as agreeing.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return (a.keys() == b.keys()
                and all(_json_equal(a[k], b[k]) for k in a))
    if isinstance(a, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    return a == b


def _accepting_branches(text, used, depth, found, seen):
    """Collect (object, repairs) for every accepting branch within the bound.

    A pass may offer several candidates — a missing quote has more than one
    plausible insertion point — and each is explored, because a disagreement
    *within* one pass is exactly as much of a guess as a disagreement between
    two. `seen` dedupes texts so the same document reached by two pass orderings
    is not enumerated (or reported) twice.
    """
    if text in seen:
        return
    seen.add(text)
    try:
        found.append((_strict_loads(text), []))
        return
    except (json.JSONDecodeError, ValueError):
        pass
    if depth <= 0:
        return
    for name, fn in _PASSES:
        if name in used:
            continue
        try:
            produced = fn(text)
        except Exception:
            produced = None
        if produced is None:
            continue
        candidates = produced if isinstance(produced, list) else [produced]
        for candidate in candidates:
            if candidate == text:
                continue
            nested = []
            _accepting_branches(candidate, used | {name}, depth - 1, nested, seen)
            found.extend((obj, [name] + rest) for obj, rest in nested)


def repair_json(text):
    """Parse `text`, repairing bounded syntax defects. → (obj, repairs, status).

    status is one of:
      `clean`        — parsed as written; `repairs` is empty and the caller may
                       stay quiet. The only status that means "nothing happened".
      `repaired`     — every accepting branch agreed; `obj` is that object and
                       `repairs` names the passes that fired.
      `ambiguous`    — accepting branches disagreed about the resulting object.
                       No object is returned: the reading cannot be established
                       from syntax alone, and picking one would be a guess.
      `unrepairable` — no branch parsed. `obj` is None.
    """
    if not isinstance(text, str) or not text.strip():
        return None, [], UNREPAIRABLE
    try:
        return _strict_loads(text), [], CLEAN
    except (json.JSONDecodeError, ValueError):
        pass

    found = []
    _accepting_branches(text, frozenset(), _MAX_DEPTH, found, set())
    if not found:
        return None, [], UNREPAIRABLE
    first = found[0][0]
    if any(not _json_equal(first, obj) for obj, _ in found[1:]):
        return None, [], AMBIGUOUS
    return first, found[0][1], REPAIRED


def load_json_repaired(path, encoding='utf-8'):
    """`repair_json` over a file. → (obj, repairs, status). Never raises on
    malformed content; an unreadable path still raises, since absence is not a
    syntax defect and must not be reported as one."""
    with open(path, encoding=encoding) as f:
        return repair_json(f.read())


def describe(repairs, status=REPAIRED):
    """One-line advisory text ('' when there is nothing to report)."""
    if status == AMBIGUOUS:
        return 'ambiguous JSON — competing repairs disagree, refusing to guess'
    if status == UNREPAIRABLE:
        return 'unrepairable JSON'
    if not repairs:
        return ''
    return f"repaired JSON ({', '.join(repairs)})"
