#!/usr/bin/env python3
"""
json_repair.py — bounded, lossless recovery for hand-authored JSON sidecars.

Every JSON file an agent writes by hand is one unescaped newline away from being
unreadable. On 2026-07-28 the brief dropped the closing quote on the last
`data_caveats` entry of `memory/.tmp/insights-2026-07-28.json`; `json.load`
raised `Invalid control character at line 48`, `build_dashboard` lost the whole
behavioural-review card group, and the daily health check went red — for one
absent byte in 4,361.

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
import json
import re

# A file can carry more than one defect, so passes compose — but only to this
# depth, and only through branches the parser accepts. With 4 passes that bounds
# the search at 4·3·2 = 24 candidates.
_MAX_DEPTH = 3

CLEAN = 'clean'
REPAIRED = 'repaired'
AMBIGUOUS = 'ambiguous'
UNREPAIRABLE = 'unrepairable'

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
    """Set of indices that are not inside any string literal (quotes included)."""
    inside = set()
    for start, end in _iter_string_spans(text):
        stop = len(text) if end is None else end + 1
        inside.update(range(start, stop))
    return set(range(len(text))) - inside


def _strip_code_fence(text):
    """```json … ``` → the payload. Deletes only the fence lines themselves."""
    m = _FENCE_RE.match(text)
    return m.group(1) if m else None


def _close_unterminated_string(text):
    """Insert the closing quote the author owed, at the end of that line.

    Handles both a span that never closes and a span that swallowed a newline —
    the two shapes a missing quote produces. Nothing is deleted; the text as
    written is preserved and only the delimiter is supplied. Declines when the
    line ends in a backslash, where the author was plainly still mid-value.
    """
    for start, end in _iter_string_spans(text):
        if end is not None and '\n' not in text[start:end]:
            continue
        nl = text.find('\n', start + 1)
        tail = text[start:] if nl == -1 else text[start:nl]
        if tail.rstrip().endswith('\\'):
            return None
        cut = start + len(tail.rstrip())
        return text[:cut] + '"' + text[cut:]
    return None


def _escape_control_chars(text):
    """Escape raw newlines/tabs that sit inside a string literal.

    In place and value-preserving: the character survives as its JSON escape.
    Only characters strictly inside a closed span are touched, so the newlines
    that format the document are untouched.
    """
    out, last, changed = [], 0, False
    for start, end in _iter_string_spans(text):
        if end is None:
            break
        body = text[start:end + 1]
        escaped = (body.replace('\n', '\\n')
                       .replace('\r', '\\r')
                       .replace('\t', '\\t'))
        if escaped != body:
            changed = True
        out.append(text[last:start])
        out.append(escaped)
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
    drop = []
    for i, ch in enumerate(text):
        if ch != ',' or i not in outside:
            continue
        j = i + 1
        while j < len(text) and text[j] in ' \t\r\n':
            j += 1
        if j < len(text) and text[j] in ']}' and j in outside:
            drop.append(i)
    if not drop:
        return None
    cut = set(drop)
    return ''.join(c for i, c in enumerate(text) if i not in cut)


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


def _accepting_branches(text, used, depth, found):
    """Collect (object, repairs) for every accepting branch within the bound."""
    try:
        found.append((json.loads(text), []))
        return
    except (json.JSONDecodeError, ValueError):
        pass
    if depth <= 0:
        return
    for name, fn in _PASSES:
        if name in used:
            continue
        try:
            candidate = fn(text)
        except Exception:
            candidate = None
        if candidate is None or candidate == text:
            continue
        nested = []
        _accepting_branches(candidate, used | {name}, depth - 1, nested)
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
        return json.loads(text), [], CLEAN
    except (json.JSONDecodeError, ValueError):
        pass

    found = []
    _accepting_branches(text, frozenset(), _MAX_DEPTH, found)
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
