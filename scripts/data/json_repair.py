#!/usr/bin/env python3
"""
json_repair.py — bounded, named recovery for LLM-authored JSON.

Every JSON file an agent writes by hand (the daily insights sidecar, the intraday
status sidecar, plan.json) is one unescaped newline away from being unreadable.
On 2026-07-28 the brief dropped the closing quote on the last `data_caveats`
entry; `json.load` raised `Invalid control character at line 48`, build_dashboard
lost the whole behavioural-review card, and the daily Cron Health Check went red
for a file that was 3038 of 3039 bytes correct.

Design rules, in priority order:

1. **Never touch valid JSON.** Strict `json.loads` runs first; if it succeeds the
   input is returned untouched with zero repairs. A repair pass can only ever run
   on text that already failed to parse.
2. **Never invent data.** Every pass either deletes a syntactic artefact (fence,
   trailing comma) or closes a structure the author left open, preserving the
   partial text as written. No pass rewrites, guesses at, or completes a *value*.
3. **Never repair silently.** `repair_json` returns the list of pass names that
   fired. Callers must surface it — a file that needs repairing every day is a
   producer bug, and a silent fixer would hide it forever (see the shared-memory
   note `feedback-detect-but-never-silence`).

Repairs are advisory, not warnings: the section rendered, so it is not degraded.
See `_record_dashboard_build` (repair_count) and `cron_health_check` for how it
reaches the daily review without turning the run red.
"""
import json
import re

# A file can carry more than one defect (a fence around a truncated body), so
# passes compose — but only up to this depth, and a composition is kept only if
# it parses. With 6 passes that bounds the search at 6·5·4 = 120 candidates,
# microseconds on files this size, and makes "repaired" mean "the parser
# accepted it", never "our heuristic liked it".
_MAX_DEPTH = 3

_FENCE_RE = re.compile(r'^\s*```(?:json|JSON)?\s*\n(.*?)\n?\s*```\s*$', re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r',(\s*[}\]])')


def _strip_code_fence(text):
    """```json … ``` → the payload. Models fence a file write surprisingly often."""
    m = _FENCE_RE.match(text)
    return m.group(1) if m else None


def _strip_prose_wrapper(text):
    """Drop chatter outside the outermost {...} / [...] the document starts with.

    Only trims at the boundaries — the first opening brace/bracket and its last
    matching partner by character. Interior content is never touched.
    """
    starts = [i for i in (text.find('{'), text.find('[')) if i != -1]
    if not starts:
        return None
    start = min(starts)
    closer = '}' if text[start] == '{' else ']'
    end = text.rfind(closer)
    if end <= start:
        return None
    # Surrounding whitespace is not prose; treating it as such would burn a pass
    # (and a reported repair name) on a file whose only sin is a trailing \n.
    if not text[:start].strip() and not text[end + 1:].strip():
        return None
    return text[start:end + 1]


def _iter_string_spans(text):
    """Yield (open_quote_index, close_quote_index_or_None) for every JSON string.

    Walks the raw text tracking escapes so a `\\"` inside a string does not read
    as a terminator. A trailing None close means the last string was never
    closed — the truncation/missing-quote case.
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


def _close_unterminated_string(text):
    """Close a string whose author dropped the final quote before a newline.

    The 2026-07-28 case: `"…决策应等数据真口径` followed by `\n  ],`. Repaired by
    inserting `"` at the end of that line — the text written stays exactly as
    written, only the delimiter the author owed is supplied. Refuses when the
    line looks mid-value (ends in `\\`) so a genuinely multi-line value is left
    for `_escape_control_chars` instead.
    """
    for start, end in _iter_string_spans(text):
        # A span that swallowed a newline is indistinguishable from a missing
        # quote by scanning alone: the opener on the broken line simply pairs
        # with the *next* line's opener. Both readings are handled — this pass
        # takes the missing-quote reading, `_escape_control_chars` takes the
        # multi-line-value reading, and `repair_json` keeps whichever parses.
        if end is not None and '\n' not in text[start:end]:
            continue
        nl = text.find('\n', start + 1)
        tail = text[start:] if nl == -1 else text[start:nl]
        if tail.rstrip().endswith('\\'):
            return None
        # Insert the quote after the last non-blank character the author wrote,
        # so trailing indentation stays outside the string.
        cut = start + len(tail.rstrip())
        return text[:cut] + '"' + text[cut:]
    return None


def _escape_control_chars(text):
    """Escape raw newlines/tabs that sit inside a string literal.

    A model writing a multi-line quote produces a literal 0x0A between the
    quotes, which is exactly what `Invalid control character` reports. Only
    characters strictly inside a span from `_iter_string_spans` are escaped, so
    the newlines that format the document are untouched.
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
    """`[1, 2, ]` → `[1, 2]`. Purely artefact removal."""
    repaired = _TRAILING_COMMA_RE.sub(r'\1', text)
    return repaired if repaired != text else None


def _close_open_containers(text):
    """Append the `}`/`]` a truncated document never got to write.

    Counts unclosed containers outside string literals and closes them in the
    right order. Also drops a dangling `"key":` or trailing comma at the cut
    point, since neither can be completed without inventing a value.
    """
    spans = [(s, e) for s, e in _iter_string_spans(text) if e is not None]

    def in_string(idx):
        return any(s <= idx <= e for s, e in spans)

    stack = []
    for i, ch in enumerate(text):
        if in_string(i):
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch in '}]':
            if stack and stack[-1] == ('{' if ch == '}' else '['):
                stack.pop()
    if not stack:
        return None
    body = text.rstrip()
    # A cut mid-pair leaves `"k":` or `"k": ` with nothing after it, and a cut
    # right after an element leaves the separator. Neither is completable.
    body = re.sub(r',\s*$', '', body)
    body = re.sub(r'"[^"\n]*"\s*:\s*$', '', body).rstrip().rstrip(',')
    return body + ''.join('}' if ch == '{' else ']' for ch in reversed(stack))


# Name → pass. Cheapest and most localised first; `unterminated_string` precedes
# `control_chars_in_string` because it is the likelier authoring slip, but that
# preference is only a tiebreak. Correctness comes from the parser, not the
# order: a dropped quote mispairs every quote after it, so the escaping reading
# of such a file does not parse and the driver backs out of it. Verified by
# mutation — swapping these two changes no test outcome.
_PASSES = (
    ('code_fence', _strip_code_fence),
    ('prose_wrapper', _strip_prose_wrapper),
    ('trailing_comma', _drop_trailing_comma),
    ('unterminated_string', _close_unterminated_string),
    ('control_chars_in_string', _escape_control_chars),
    ('truncated_document', _close_open_containers),
)


def _search(text, used, depth):
    """Depth-first over unused passes; a branch counts only when it parses.

    Returns (obj, repairs) for the first branch the parser accepts, else
    (None, []) — deliberately not the deepest partial attempt, because a list of
    repairs that did not produce valid JSON would misreport what happened.
    """
    try:
        return json.loads(text), []
    except (json.JSONDecodeError, ValueError):
        pass
    if depth <= 0:
        return None, []
    for name, fn in _PASSES:
        if name in used:
            continue
        try:
            candidate = fn(text)
        except Exception:
            candidate = None
        if candidate is None or candidate == text:
            continue
        obj, rest = _search(candidate, used | {name}, depth - 1)
        if obj is not None:
            return obj, [name] + rest
    return None, []


def repair_json(text):
    """Parse `text`, repairing bounded syntax defects. → (obj_or_None, repairs).

    `repairs` is the ordered list of pass names that fired; it is empty when the
    input parsed strictly, which is the only case where the caller may stay
    quiet. A None object means the text was beyond these passes — the caller
    keeps its existing failure path.
    """
    if not isinstance(text, str) or not text.strip():
        return None, []
    # The strict-parse guarantee lives in `_search`'s first statement, so valid
    # input returns before any pass runs. Do not re-add it here: a duplicate
    # fast path reads like a safety net while being unreachable, and a mutation
    # run proved deleting it changed nothing.
    return _search(text, frozenset(), _MAX_DEPTH)


def load_json_repaired(path, encoding='utf-8'):
    """`repair_json` over a file. → (obj_or_None, repairs). Never raises on
    malformed content; an unreadable path still raises, since that is not a
    syntax defect and must not be mistaken for one."""
    with open(path, encoding=encoding) as f:
        return repair_json(f.read())


def describe(repairs):
    """One-line advisory text for a repair list ('' when nothing fired)."""
    return f"repaired JSON ({', '.join(repairs)})" if repairs else ''
