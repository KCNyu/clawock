#!/usr/bin/env python3
"""Output-side gate for the four LLM call sites (#1265).

`llm.chat()` is the transport: it retries, falls back between two vendors and
strips fences. What it returns is still *whatever the model said* — a string.
Every call site consumed that string directly, so a vendor that answers 200 with
an empty body, prose instead of the requested markdown, or JSON whose fields are
out of range published a blank/garbled artifact instead of failing.

Two shapes, one rule — **an unusable output is refused, never published**:

- `validate_sections()` for the three free-text markdown outputs (brief
  fallback #1262, weekly review #1263, news digest #1264). It checks the two
  things a wrong answer actually breaks: the output is not empty/stub-length,
  and the sections the prompt demanded are present. It deliberately does not
  grade prose — the model's judgment is the product there.
- `coerce_scored_items()` for the one structured output (influencer #1257).
  It is *coercing*, not fail-closed, because that call site's alternative to a
  slightly-off item is no radar at all: a bad `idx` skips that one item instead
  of raising out of the whole batch (today one non-int `idx` raises inside the
  dict comprehension and loses every scored item), an unknown `stance` degrades
  to `neutral`, an out-of-range `relevance` is clamped, and hallucinated keys
  are dropped rather than shipped into `influencer.json`.

Anchors are substrings, not exact headings: the fallback brief writes
`## ▎仓位明细 (HK)` while the harness renders `## ▎仓位明细`, and the digest
answers `## 风险 Watch` to a prompt that asked for `风险 watch`. Requiring exact
titles would fail closed on good output, which is the expensive direction —
`tests/test_llm_output_validate.py` pins each anchor set against a real
committed artifact for exactly that reason.
"""
from __future__ import annotations

import sys

# influencer.py's LLM_SYSTEM defines this enum; anything else is the model
# inventing a variant ("BULLISH", "positive"), which used to reach the brief
# and the evidence graph as display text.
INFLUENCER_STANCES = ('endorse', 'buy', 'attack', 'sell', 'neutral')
# Exact key set the prompt asks for. Extra keys are model hallucination and
# would ride into influencer.json (payload bloat, no consumer).
INFLUENCER_ITEM_FIELDS = (
    'idx', 'tickers', 'held', 'new_ideas', 'sectors', 'sector_holdings',
    'stance', 'relevance', 'summary_cn',
)
INFLUENCER_LIST_FIELDS = ('tickers', 'held', 'new_ideas', 'sectors',
                          'sector_holdings')


class LLMOutputError(ValueError):
    """A model reply that must not be published."""


def validate_sections(text, *, label, required, min_chars):
    """Return `text` unchanged, or raise `LLMOutputError`.

    `required` is a sequence of substrings that must all appear (matched
    case-insensitively so `Per-ticker`/`per-ticker` both pass). `min_chars`
    guards the empty/stub reply — set it an order of magnitude below the real
    artifact so a short-but-real answer is never refused.
    """
    body = (text or '').strip()
    if not body:
        raise LLMOutputError(f'{label}: model returned an empty reply')
    if len(body) < min_chars:
        raise LLMOutputError(
            f'{label}: model returned {len(body)} chars, below the '
            f'{min_chars}-char floor for a usable output')
    lowered = body.lower()
    missing = [anchor for anchor in required if anchor.lower() not in lowered]
    if missing:
        raise LLMOutputError(
            f'{label}: missing required section(s): ' + ', '.join(missing))
    return text


def _clean_str_list(value):
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clamp_relevance(value, report):
    """0-100 per the prompt. Out of range is clamped (the field is a sort key,
    so 150 silently outranks every honest 95); non-numeric becomes None, which
    the caller already treats as "unscored"."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is not None:
            report['relevance_dropped'] += 1
        return None
    clamped = max(0.0, min(100.0, float(value)))
    if clamped != float(value):
        report['relevance_clamped'] += 1
    return int(clamped) if clamped == int(clamped) else clamped


_DEFAULT_REPORT = object()


def coerce_scored_items(data, *, report_to=_DEFAULT_REPORT):
    """`{idx: item}` from a parsed `{"items":[...]}` reply, field-checked.

    Never raises for item-level damage: a malformed item is skipped and
    counted. Raises `LLMOutputError` only when the top-level shape is wrong
    (not an object, or `items` is not a list), which is a parse-level failure
    the caller already retries.
    """
    if not isinstance(data, dict):
        raise LLMOutputError(f'expected a JSON object, got {type(data).__name__}')
    items = data.get('items', [])
    if not isinstance(items, list):
        raise LLMOutputError(f'"items" must be a list, got {type(items).__name__}')

    report = {'bad_idx': 0, 'unknown_stance': 0, 'relevance_clamped': 0,
              'relevance_dropped': 0, 'extra_fields': 0, 'duplicate_idx': 0}
    scored = {}
    for raw in items:
        if not isinstance(raw, dict):
            report['bad_idx'] += 1
            continue
        try:
            idx = int(raw['idx'])
        except (KeyError, TypeError, ValueError):
            report['bad_idx'] += 1
            continue
        if any(key not in INFLUENCER_ITEM_FIELDS for key in raw):
            report['extra_fields'] += 1
        stance = str(raw.get('stance', 'neutral') or 'neutral').strip().lower()
        if stance not in INFLUENCER_STANCES:
            report['unknown_stance'] += 1
            stance = 'neutral'
        item = {'idx': idx, 'stance': stance,
                'relevance': _clamp_relevance(raw.get('relevance'), report),
                'summary_cn': str(raw.get('summary_cn', '') or '').strip()}
        for field in INFLUENCER_LIST_FIELDS:
            item[field] = _clean_str_list(raw.get(field))
        if idx in scored:
            report['duplicate_idx'] += 1
        scored[idx] = item

    if report_to is _DEFAULT_REPORT:
        # Resolved per call, not bound at import: a default of `sys.stderr`
        # captures the real stream before pytest's capsys swaps it out.
        report_to = sys.stderr
    if report_to is not None:
        problems = {k: v for k, v in report.items() if v}
        if problems:
            print('  ⚠️ LLM output coerced: '
                  + ', '.join(f'{k}={v}' for k, v in sorted(problems.items())),
                  file=report_to)
    return scored
