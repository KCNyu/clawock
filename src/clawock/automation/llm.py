#!/usr/bin/env python3
"""
Minimal LLM client for KCNyu GitHub Actions workflows.

Provider: MiniMax M3 over the Anthropic Messages protocol. Used by
brief-fallback / weekly-review / news-digest / influencer-scan — none of which
can reach the local openclaw gateway, so they call the vendor API directly.

History:
- 2026-06-01 (kcn "都改吧变成稳妥的anthropic的"): both providers onto the
  Anthropic Messages transport (at the time Xiaomi + MiniMax).
- 2026-08-16 (#695/#697): Xiaomi's key died; the fallback became opencode-go's
  DeepSeek V4 Flash over an OpenAI-compatible `/chat/completions` shape.
- 2026-09-13 (kcn「opencode 可以都移除」): the OpenCode wallet had been empty
  since at least 2026-09-02 — every time MiniMax failed, the fallback answered
  `HTTP 401 CreditsError`, so it was never a second chance, only a second
  error line. It is gone, with its wire shape. MiniMax is the only provider;
  there is no paid pay-as-you-go leg anywhere in this client by decision.

Env:
- MINIMAX_API_KEY   — required

Notes:
- MiniMax (Anthropic Messages): system is a TOP-LEVEL param, not a message
  role — `_split_system` lifts it out. thinking is a first-class block.
- thinking: enabled by default (better prose quality). For structured JSON
  extraction pass thinking_disabled=True — reasoning budget competing with the
  output cap truncates JSON, and a deterministic extraction wants thinking off.
- json_response: no response_format param is leaned on; we instruct JSON in the
  prompt and pull the first balanced {…}/[…] out of the reply via _extract_json
  (fence- and stray-prose-tolerant).
- ANTHROPIC_VERSION header pinned to 2023-06-01 (what MiniMax accepts).

Usage:
    from clawock.automation.llm import chat
    reply = chat(system="...", user="...", max_tokens=32000)
"""
import os
import re
import sys
import time

import requests

# Module-level session: retries reuse one connection pool instead of a fresh
# TCP+TLS handshake per attempt (C-F2).
_SESSION = requests.Session()

MINIMAX_BASE = 'https://api.minimaxi.com/anthropic'
MINIMAX_MODEL = 'MiniMax-M3'
MINIMAX_MAX_TOKENS = 131072  # M3 maxOutput
ANTHROPIC_VERSION = '2023-06-01'
TIMEOUT = 180  # 3 min per call
MAX_RETRIES = 3

# A total wall-clock budget for the whole call, in seconds.
#
# Without one the retry ladder can be longer than the job that contains it.
# Measured on 2026-08-17 (release run 31985473431): brief_fallback calls chat()
# with timeout=900 and MAX_RETRIES is 3, so MiniMax alone may spend 45 minutes
# inside a job whose `timeout-minutes` is 15 — the runner killed the job
# mid-retry and nothing was written, not even the error.
#
# Set it from the workflow that knows its own job budget, via
# CLAWOCK_LLM_DEADLINE_SECONDS, or pass deadline_seconds= explicitly. Unset
# keeps the historical behaviour exactly. With a single provider the whole
# budget is the provider's; there is no longer a share reserved for a fallback.
DEADLINE_ENV = 'CLAWOCK_LLM_DEADLINE_SECONDS'


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
    strings. Models sometimes wrap JSON in a ```json fence or add a stray prose
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
    """Seconds left before the call must give up, or None."""
    if deadline is None:
        return None
    return deadline - time.monotonic()


def _attempt_timeout(timeout, deadline, label):
    """Per-attempt timeout clamped to the budget, or None when out of time.

    Returning None rather than sleeping-then-failing matters: an attempt that
    cannot finish inside the job only turns a clean error into a killed runner.
    """
    left = _remaining(deadline)
    if left is None:
        return timeout
    if left <= 1:
        print(f'  {label}: budget exhausted — giving up', file=sys.stderr)
        return None
    return max(1, min(timeout, int(left)))


def _backoff(seconds, deadline, label):
    """Sleep between attempts without sleeping past the budget."""
    left = _remaining(deadline)
    if left is not None:
        seconds = min(seconds, max(0.0, left))
    if seconds > 0:
        time.sleep(seconds)


class _RateLimited(Exception):
    """The provider answered 429: sleep the linear wait, retry."""

    def __init__(self, wait):
        super().__init__('429 rate limit')
        self.wait = wait


class _HTTPErr(Exception):
    """Non-200/429 answer; str() is exactly the historical last_err text."""


def _run_with_retries(label, timeout, deadline, once, attempts_sink=None):
    """Retry skeleton (C-F5).

    once(attempt, per_attempt) returns the assistant content string on a 200,
    raises _RateLimited on 429 (linear wait, no extra generic backoff), and
    may raise anything else — that becomes this attempt's recorded error.

    attempts_sink: optional list; receives the number of attempts actually
    run when the call settles either way (C-F3a stats).
    """
    last_err = None
    attempts_run = 0
    for attempt in range(1, MAX_RETRIES + 1):
        per_attempt = _attempt_timeout(timeout, deadline, label)
        if per_attempt is None:
            last_err = last_err or 'budget exhausted before any attempt completed'
            break
        attempts_run = attempt
        try:
            content = once(attempt, per_attempt)
            if attempts_sink is not None:
                attempts_sink.append(attempt)
            return content
        except requests.Timeout:
            last_err = f'timeout after {per_attempt}s'
            print(f'  {label}: {last_err} (attempt {attempt})', file=sys.stderr)
        except _RateLimited as rl:
            print(f'  {label}: 429 rate limit, sleeping {rl.wait}s', file=sys.stderr)
            _backoff(rl.wait, deadline, label)
            continue
        except _HTTPErr as he:
            last_err = str(he)
            print(f'  {label}: {last_err}', file=sys.stderr)
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            print(f'  {label}: {last_err}', file=sys.stderr)
        _backoff(2 * attempt, deadline, label)
    if attempts_sink is not None:
        attempts_sink.append(attempts_run)
    raise RuntimeError(f'{label} failed after {MAX_RETRIES} attempts: {last_err}')


def _call_provider(label, base_url, api_key, model, messages, max_tokens,
                   temperature, json_response, thinking, timeout=None,
                   deadline=None, attempts_sink=None):
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
        # Some Anthropic-compatible endpoints default thinking ON when the field
        # is omitted (burns the output budget on reasoning), so disable explicitly.
        body['thinking'] = {'type': 'disabled'}

    headers = {
        'x-api-key': api_key,
        'anthropic-version': ANTHROPIC_VERSION,
        'Content-Type': 'application/json',
    }

    def once(attempt, per_attempt):
        r = _SESSION.post(f'{base_url}/v1/messages',
                          json=body, headers=headers, timeout=per_attempt)
        if r.status_code == 429:
            raise _RateLimited(5 * attempt)
        if r.status_code != 200:
            raise _HTTPErr(f'HTTP {r.status_code}: {r.text[:300]}')
        data = r.json()
        blocks = data.get('content', []) or []
        text = ''.join(b.get('text', '') for b in blocks
                       if b.get('type') == 'text')
        usage = data.get('usage', {}) or {}
        print(f'  {label}: {usage.get("input_tokens","?")} in / '
              f'{usage.get("output_tokens","?")} out '
              f'(stop={data.get("stop_reason","?")})', file=sys.stderr)
        if not text:
            # A thinking block is the model's reasoning, not its answer — a
            # reply that ran out of tokens before any text is exactly this
            # shape. It used to be returned as the answer, and the section
            # checks downstream are substring checks reasoning can pass
            # (#1923). No answer is a failed attempt; the retry ladder decides.
            raise _HTTPErr(f'no text block in the reply '
                           f'(stop={data.get("stop_reason","?")})')
        cleaned = _clean(text)
        return _extract_json(cleaned) if json_response else cleaned

    return _run_with_retries(label, timeout, deadline, once,
                             attempts_sink=attempts_sink)


def chat(system: str = '', user: str = '', messages: list = None,
         max_tokens: int = 32000, temperature: float = 0.7,
         thinking_disabled: bool = False, json_response: bool = False,
         timeout: int = None, deadline_seconds: float = None,
         stats_out: dict = None) -> str:
    """Call MiniMax M3. Returns the assistant content string, or raises
    RuntimeError('all LLM providers failed: …') when it fails — the prefix is
    what callers (influencer.llm_filter) match to stop retrying a dead chain.

    timeout: per-attempt seconds, default TIMEOUT (180). Big jobs need more: the
    daily brief prefills ~100KB of context and generates ~20K tokens with thinking
    on, which blew straight through 180s x3 on 2026-07-16. Raise it rather than
    shrink the prompt — trimming the brief's context made it blind to half the book.

    deadline_seconds: total wall clock for the call, defaulting to
    CLAWOCK_LLM_DEADLINE_SECONDS. `timeout` alone cannot keep the retries inside
    the job that contains them — timeout x MAX_RETRIES is the real budget.

    stats_out: when given, receives {'legs': [{provider, ok, attempts, wall_s,
    error?}]} so a job log can say what the call actually cost (C-F3a).
    """
    if messages is None:
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        if user:
            messages.append({'role': 'user', 'content': user})

    thinking = {'type': 'disabled'} if thinking_disabled else {'type': 'enabled'}

    if deadline_seconds is None:
        raw = os.environ.get(DEADLINE_ENV)
        if raw:
            try:
                deadline_seconds = float(raw)
            except ValueError:
                print(f'  ⚠️ {DEADLINE_ENV}={raw!r} is not a number — ignoring',
                      file=sys.stderr)
    deadline = None if not deadline_seconds else time.monotonic() + float(deadline_seconds)

    mm_key = os.environ.get('MINIMAX_API_KEY')
    if not mm_key:
        raise RuntimeError('all LLM providers failed: minimax[no MINIMAX_API_KEY]')

    def call(**kw):
        return _call_provider(
            'minimax', MINIMAX_BASE, mm_key, MINIMAX_MODEL,
            messages, min(max_tokens, MINIMAX_MAX_TOKENS),
            temperature, json_response, thinking, timeout,
            deadline=deadline, **kw)

    t0 = time.monotonic()
    # _run_with_retries appends ONE value to the sink when it settles: the
    # attempt that succeeded, or how many attempts ran before it gave up. The
    # count is that value, not the list's length (which is always 1).
    attempts = []
    try:
        # Zero-overhead path when nobody asked for stats: no extra kwarg
        # reaches a test double of _call_provider.
        out = call() if stats_out is None else call(attempts_sink=attempts)
    except Exception as e:
        if stats_out is not None:
            stats_out.setdefault('legs', []).append(
                {'provider': 'minimax', 'ok': False,
                 'attempts': attempts[-1] if attempts else 0,
                 'wall_s': round(time.monotonic() - t0, 2), 'error': str(e)[:160]})
        raise RuntimeError(f'all LLM providers failed: minimax[{e}]') from e
    if stats_out is not None:
        stats_out.setdefault('legs', []).append(
            {'provider': 'minimax', 'ok': True,
             'attempts': attempts[-1] if attempts else 0,
             'wall_s': round(time.monotonic() - t0, 2)})
    return out


if __name__ == '__main__':
    # Sanity test: cli example
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--system', default='You are a helpful stock analyst.')
    ap.add_argument('--user', required=True)
    ap.add_argument('--max-tokens', type=int, default=2000)
    args = ap.parse_args()
    print(chat(system=args.system, user=args.user, max_tokens=args.max_tokens))
