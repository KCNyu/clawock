#!/usr/bin/env python3
"""
Minimal LLM client for KCNyu GitHub Actions workflows.

Primary: MiniMax M3 (Anthropic Messages protocol). Fallback: OpenCode Zen's
DeepSeek V4 Flash (OpenAI-compatible protocol — https://opencode.ai/docs/zen).
The two providers do NOT share a wire protocol, so this module carries two
request/response shapes: `_call_provider` speaks Anthropic `/v1/messages` for
MiniMax; `_call_provider_openai_compatible` speaks `/chat/completions` for
OpenCode Zen. Used by brief-fallback / weekly-review / news-digest /
influencer-scan — none of which can reach the local openclaw gateway, so they
call the vendor API directly.

Why a fallback (2026-05-30, kcn 要求): one vendor can hit empty-turn,
sensitive-content or rate-limit failures that blank a scheduled job. MiniMax is
primary; OpenCode Zen / DeepSeek V4 Flash is the fallback.

History:
- 2026-06-01 (kcn "都改吧变成稳妥的anthropic的"): switched both providers onto
  the Anthropic Messages transport (see memory/openclaw-xiaomi-fallback.md) —
  at the time both legs were Xiaomi/MiniMax and both spoke that protocol.
- 2026-08-16 (kcn "xiaomi的早没了 你换成我opencode go的ds flash吧", issue
  #695/#697): Xiaomi's token-plan key had already died (HTTP 401) — its
  retirement, predicted in this docstring since 2026-06, finally landed.
  Fallback swapped to opencode-go's DeepSeek V4 Flash, which is OpenAI-
  compatible rather than Anthropic — bringing a `/chat/completions` shape back
  for the fallback leg only.

Env:
- MINIMAX_API_KEY   — primary
- OPENCODE_API_KEY  — fallback (optional; if unset, the fallback is skipped)

Notes:
- MiniMax (Anthropic Messages): system is a TOP-LEVEL param, not a message
  role — `_split_system` lifts it out. thinking is a first-class block.
- opencode-go (OpenAI-compatible): system stays inline as a message role;
  reasoning (if any) rides along as `reasoning_content` on the assistant
  message rather than a separate typed block — we don't read it, only
  `content`.
- thinking: enabled by default for MiniMax (better prose quality). For
  structured JSON extraction pass thinking_disabled=True — reasoning budget
  competing with the output cap truncates JSON, and a deterministic extraction
  wants thinking off. opencode-go has no equivalent knob wired through here.
- json_response: neither vendor has a response_format param we lean on, so we
  just instruct JSON in the prompt and pull the first balanced {…}/[…] out of
  the reply via _extract_json (fence- and stray-prose-tolerant).
- ANTHROPIC_VERSION header pinned to 2023-06-01 (what MiniMax accepts).

Usage:
    from clawock.automation.llm import chat
    reply = chat(system="...", user="...", max_tokens=32000)
"""
import json
import os
import re
import sys
import time

import requests

# Module-level session: provider legs reuse one connection pool instead of a
# fresh TCP+TLS handshake per attempt (C-F2). Retry chains are exactly where
# this pays — the fallback leg often fires seconds after the primary died.
_SESSION = requests.Session()

MINIMAX_BASE = 'https://api.minimaxi.com/anthropic'
MINIMAX_MODEL = 'MiniMax-M3'
MINIMAX_MAX_TOKENS = 131072  # M3 maxOutput
# OpenAI-compatible endpoint (base, no trailing /chat/completions — added per call).
OPENCODE_BASE = 'https://opencode.ai/zen/v1'
OPENCODE_MODEL = 'deepseek-v4-flash'
# Vendor cap is 384000 (see /root/.cache/opencode/models.json), but this is a
# last-resort fallback, not a primary route — keep it in the same conservative
# range the old Xiaomi fallback used rather than trusting the full vendor cap.
OPENCODE_MAX_TOKENS = 32000
ANTHROPIC_VERSION = '2023-06-01'
TIMEOUT = 180  # 3 min per call
MAX_RETRIES = 3

# A total wall-clock budget shared by the whole provider chain, in seconds.
#
# Without one the retry ladder can be longer than the job that contains it, and
# then the second provider is not a fallback — it is unreachable code. Measured
# on 2026-08-17 (release run 31985473431): brief_fallback calls chat() with
# timeout=900 and MAX_RETRIES is 3, so MiniMax alone may spend 45 minutes inside
# a job whose `timeout-minutes` is 15. MiniMax hit RemoteDisconnected, started
# retrying, and the runner killed the job before opencode-go was ever asked.
# Every manual dispatch of that workflow failed the same way, which is why a
# backstop nobody had ever seen produce output looked merely untested rather
# than broken.
#
# Set it from the workflow that knows its own job budget, via
# CLAWOCK_LLM_DEADLINE_SECONDS, or pass deadline_seconds= explicitly. Unset
# keeps the historical behaviour exactly.
DEADLINE_ENV = 'CLAWOCK_LLM_DEADLINE_SECONDS'
# The share of the budget the primary may consume before the chain moves on.
# The remainder is reserved for the fallback, so a slow primary can cost the
# run quality but never the fallback's chance to answer.
PRIMARY_BUDGET_SHARE = 0.6


def _clean(s: str) -> str:
    """Strip a leading assistant-prefill artifact and an outer ```/```json fence
    so prose and json.loads both work. (Anthropic returns thinking as a separate
    block, so no inline <think> to strip — but we defensively drop it anyway.)"""
    t = (s or '')
    if '</think>' in t:
        t = t[t.rindex('</think>') + len('</think>'):]
    t = re.sub(r'<think>.*?</think>', '', t, flags=re.S).strip()
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\n?', '', t)
        t = re.sub(r'\n?```$', '', t.strip())
    return t.strip()


def _extract_json(t):
    """Return the first balanced {…} / […] value in t, ignoring braces inside
    strings. mimo sometimes wraps JSON in a ```json fence or adds a stray prose
    line; this pulls out the parseable value. Returns t unchanged if none found."""
    starts = [i for i in (t.find('{'), t.find('[')) if i != -1]
    if not starts:
        return t
    start = min(starts)
    open_ch = t[start]
    close_ch = '}' if open_ch == '{' else ']'
    depth = 0
    in_str = esc = False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return t[start:i + 1]
    return t[start:]


def _split_system(messages):
    """Lift any system-role messages to a top-level system string (Anthropic puts
    system outside the messages array). Returns (system_str, non_system_messages)."""
    sys_parts, rest = [], []
    for m in messages:
        if m.get('role') == 'system':
            sys_parts.append(m.get('content', ''))
        else:
            rest.append({'role': m['role'], 'content': m['content']})
    return '\n\n'.join(p for p in sys_parts if p), rest


def _remaining(deadline):
    """Seconds left before the chain must give up on this provider, or None."""
    if deadline is None:
        return None
    return deadline - time.monotonic()


def _attempt_timeout(timeout, deadline, label):
    """Per-attempt timeout clamped to the budget, or None when out of time.

    Returning None rather than sleeping-then-failing matters: the point of the
    budget is to hand the remaining seconds to the next provider while there
    are still seconds to hand over.
    """
    left = _remaining(deadline)
    if left is None:
        return timeout
    if left <= 1:
        print(f'  {label}: budget exhausted — yielding to the next provider',
              file=sys.stderr)
        return None
    return max(1, min(timeout, int(left)))


def _backoff(seconds, deadline, label):
    """Sleep between attempts without spending the next provider's seconds.

    An un-clamped backoff is the same bug as an un-clamped timeout, only more
    embarrassing: the budget gets burned doing nothing at all.
    """
    left = _remaining(deadline)
    if left is not None:
        seconds = min(seconds, max(0.0, left))
    if seconds > 0:
        time.sleep(seconds)


def _call_provider(label, base_url, api_key, model, messages, max_tokens,
                   temperature, json_response, thinking, timeout=None,
                   deadline=None):
    """One provider over Anthropic Messages, with retries. Returns content str
    or raises RuntimeError."""
    timeout = timeout or TIMEOUT
    system_str, msgs = _split_system(messages)

    thinking_on = bool(thinking) and thinking.get('type') == 'enabled'

    body = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': msgs,
    }
    if system_str:
        body['system'] = system_str
    if thinking_on:
        # Anthropic requires temperature==1 when thinking is enabled, and
        # budget_tokens strictly less than max_tokens.
        body['temperature'] = 1.0
        body['thinking'] = {
            'type': 'enabled',
            'budget_tokens': max(1024, min(max_tokens - 1024, 16000)),
        }
    else:
        body['temperature'] = temperature
        # mimo's Anthropic endpoint defaults thinking ON when the field is
        # omitted (burns the output budget on reasoning), so disable explicitly.
        body['thinking'] = {'type': 'disabled'}

    headers = {
        'x-api-key': api_key,
        'anthropic-version': ANTHROPIC_VERSION,
        'Content-Type': 'application/json',
    }

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        per_attempt = _attempt_timeout(timeout, deadline, label)
        if per_attempt is None:
            last_err = last_err or 'budget exhausted before any attempt completed'
            break
        try:
            r = _SESSION.post(f'{base_url}/v1/messages',
                              json=body, headers=headers, timeout=per_attempt)
            if r.status_code == 200:
                data = r.json()
                blocks = data.get('content', []) or []
                text = ''.join(b.get('text', '') for b in blocks
                               if b.get('type') == 'text')
                if not text:  # last resort: some endpoints surface only thinking
                    text = ''.join(b.get('thinking', '') for b in blocks
                                   if b.get('type') == 'thinking')
                usage = data.get('usage', {}) or {}
                print(f'  {label}: {usage.get("input_tokens","?")} in / '
                      f'{usage.get("output_tokens","?")} out '
                      f'(stop={data.get("stop_reason","?")})', file=sys.stderr)
                cleaned = _clean(text)
                return _extract_json(cleaned) if json_response else cleaned
            elif r.status_code == 429:
                wait = 5 * attempt
                print(f'  {label}: 429 rate limit, sleeping {wait}s', file=sys.stderr)
                _backoff(wait, deadline, label)
                continue
            else:
                last_err = f'HTTP {r.status_code}: {r.text[:300]}'
                print(f'  {label}: {last_err}', file=sys.stderr)
        except requests.Timeout:
            last_err = f'timeout after {per_attempt}s'
            print(f'  {label}: {last_err} (attempt {attempt})', file=sys.stderr)
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            print(f'  {label}: {last_err}', file=sys.stderr)
        _backoff(2 * attempt, deadline, label)
    raise RuntimeError(f'{label} failed after {MAX_RETRIES} attempts: {last_err}')


def _call_provider_openai_compatible(label, base_url, api_key, model, messages,
                                     max_tokens, temperature, json_response,
                                     timeout=None, deadline=None):
    """One provider over the OpenAI-compatible /chat/completions shape, with
    retries. Returns content str or raises RuntimeError. Unlike Anthropic
    Messages: system stays inline as a message role (no lift-out needed), and
    there is no first-class thinking block — reasoning (if any) rides along as
    `reasoning_content` on the assistant message, which we don't read. The
    Anthropic leg's `thinking` knob has no equivalent here; it was previously
    accepted and silently ignored (C-F4)."""
    timeout = timeout or TIMEOUT
    body = {
        'model': model,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'messages': messages,
    }
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        per_attempt = _attempt_timeout(timeout, deadline, label)
        if per_attempt is None:
            last_err = last_err or 'budget exhausted before any attempt completed'
            break
        try:
            r = _SESSION.post(f'{base_url}/chat/completions',
                              json=body, headers=headers, timeout=per_attempt)
            if r.status_code == 200:
                data = r.json()
                choices = data.get('choices', []) or []
                msg = choices[0].get('message', {}) if choices else {}
                text = msg.get('content', '') or ''
                usage = data.get('usage', {}) or {}
                print(f'  {label}: {usage.get("prompt_tokens","?")} in / '
                      f'{usage.get("completion_tokens","?")} out '
                      f'(finish={choices[0].get("finish_reason","?") if choices else "?"})',
                      file=sys.stderr)
                cleaned = _clean(text)
                return _extract_json(cleaned) if json_response else cleaned
            elif r.status_code == 429:
                wait = 5 * attempt
                print(f'  {label}: 429 rate limit, sleeping {wait}s', file=sys.stderr)
                _backoff(wait, deadline, label)
                continue
            else:
                last_err = f'HTTP {r.status_code}: {r.text[:300]}'
                print(f'  {label}: {last_err}', file=sys.stderr)
        except requests.Timeout:
            last_err = f'timeout after {per_attempt}s'
            print(f'  {label}: {last_err} (attempt {attempt})', file=sys.stderr)
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            print(f'  {label}: {last_err}', file=sys.stderr)
        _backoff(2 * attempt, deadline, label)
    raise RuntimeError(f'{label} failed after {MAX_RETRIES} attempts: {last_err}')


def chat(system: str = '', user: str = '', messages: list = None,
         max_tokens: int = 32000, temperature: float = 0.7,
         fallback_model: str = OPENCODE_MODEL,
         fallback_base_url: str = OPENCODE_BASE,
         fallback_api_key: str = None, thinking_disabled: bool = False,
         json_response: bool = False, fallback: bool = True,
         timeout: int = None, deadline_seconds: float = None) -> str:
    """Call MiniMax M3; on total failure fall back to opencode-go's DeepSeek V4
    Flash. The two are NOT the same wire protocol (Anthropic Messages vs
    OpenAI-compatible) — see module docstring. Returns assistant content
    string, or raises if BOTH providers fail. Set fallback=False to use
    MiniMax only (no opencode-go fallback).

    Naming is load-bearing (C-F4): `fallback_model/base_url/api_key` apply ONLY
    to the opencode-go fallback leg. The primary provider and its endpoint are
    MINIMAX_* module constants by decree — the old generic names (`model=`,
    `base_url=`) read as if they retargeted the primary and silently did not;
    the four call sites passed none of them.

    timeout: per-attempt seconds, default TIMEOUT (180). Big jobs need more: the
    daily brief prefills ~100KB of context and generates ~20K tokens with thinking
    on, which blew straight through 180s x3 on 2026-07-16 (callers see the retries
    as "timeout after Ns (attempt N)"). Raise it rather than shrink the prompt —
    trimming the brief's context is what made it blind to half the book.

    deadline_seconds: total wall clock for the WHOLE chain, defaulting to
    CLAWOCK_LLM_DEADLINE_SECONDS. `timeout` alone cannot keep the chain inside
    the job that contains it — timeout x MAX_RETRIES is the primary's budget,
    and on 2026-08-17 that was 45 minutes inside a 15-minute job, so opencode-go
    was never reached even once. With a budget set, the primary is capped at
    PRIMARY_BUDGET_SHARE of it and the remainder belongs to the fallback: a slow
    primary can cost quality, never the fallback's chance to answer.
    """
    if messages is None:
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        if user:
            messages.append({'role': 'user', 'content': user})

    thinking = {'type': 'disabled'} if thinking_disabled else {'type': 'enabled'}
    errors = []

    if deadline_seconds is None:
        raw = os.environ.get(DEADLINE_ENV)
        if raw:
            try:
                deadline_seconds = float(raw)
            except ValueError:
                print(f'  ⚠️ {DEADLINE_ENV}={raw!r} is not a number — ignoring',
                      file=sys.stderr)
    started = time.monotonic()
    chain_deadline = None if not deadline_seconds else started + float(deadline_seconds)
    primary_deadline = (None if chain_deadline is None
                        else started + float(deadline_seconds) * PRIMARY_BUDGET_SHARE)

    # ── Primary: MiniMax M3 (Anthropic Messages) ──
    mm_key = os.environ.get('MINIMAX_API_KEY')
    if mm_key:
        try:
            return _call_provider('minimax', MINIMAX_BASE, mm_key, MINIMAX_MODEL,
                                  messages, min(max_tokens, MINIMAX_MAX_TOKENS),
                                  temperature, json_response, thinking, timeout,
                                  deadline=primary_deadline)
        except Exception as e:
            errors.append(f'minimax[{e}]')
            print('  ⚠️ minimax exhausted — falling back to OpenCode Zen DeepSeek V4 Flash',
                  file=sys.stderr)
    else:
        errors.append('minimax[no MINIMAX_API_KEY]')

    # ── Fallback: OpenCode Zen / DeepSeek V4 Flash (OpenAI-compatible) ──
    # 2026-08-16, kcn: Xiaomi's token-plan key had already died (HTTP 401,
    # issue #695) — swapped the fallback to opencode-go's DeepSeek V4 Flash
    # (issue #697). If unset, the fallback is auto-skipped (no OPENCODE_API_KEY).
    opencode_key = (fallback_api_key
                    or os.environ.get('OPENCODE_API_KEY'))
    if fallback and opencode_key:
        try:
            return _call_provider_openai_compatible(
                'opencode', fallback_base_url, opencode_key, fallback_model,
                messages, min(max_tokens, OPENCODE_MAX_TOKENS),
                temperature, json_response, timeout,
                deadline=chain_deadline)
        except Exception as e:
            errors.append(f'opencode[{e}]')
    elif fallback and not opencode_key:
        errors.append('opencode[no OPENCODE_API_KEY]')

    raise RuntimeError('all LLM providers failed: ' + ' | '.join(errors))


if __name__ == '__main__':
    # Sanity test: cli example
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--system', default='You are a helpful stock analyst.')
    ap.add_argument('--user', required=True)
    ap.add_argument('--max-tokens', type=int, default=2000)
    args = ap.parse_args()
    print(chat(system=args.system, user=args.user, max_tokens=args.max_tokens))
