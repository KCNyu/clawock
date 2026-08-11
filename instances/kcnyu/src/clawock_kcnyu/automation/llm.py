#!/usr/bin/env python3
"""
Minimal Anthropic-Messages client for KCNyu GitHub Actions workflows.

Primary: MiniMax M3. Fallback: Xiaomi MiMo v2.5-pro (only while its token-plan
key still works — being retired 2026-06-16 as the plan expires; auto-skipped once
XIAOMI_API_KEY is gone). BOTH speak the Anthropic Messages protocol — the same
transport openclaw's gateway uses — which is the stable path: thinking is a
first-class block (no reasoning_content replay 400s, no empty-turn ambiguity).
Used by brief-fallback / weekly-review / news-digest / influencer-scan — none of
which can reach the local openclaw gateway, so they call the vendor API directly.

Why a fallback (2026-05-30, kcn 要求): one vendor can hit empty-turn,
sensitive-content or rate-limit failures that blank a scheduled job. MiniMax is now
primary; while the optional Xiaomi key remains usable it provides a second route.

Migration (2026-06-01, kcn "都改吧变成稳妥的anthropic的"): switched off the old
OpenAI /v1/chat/completions transport. MiniMax M2.7 + openai-completions is dead
(see memory/openclaw-xiaomi-fallback.md) — that fallback used to be a no-op. Now
both providers POST {base}/v1/messages with x-api-key + anthropic-version.

Env:
- MINIMAX_API_KEY  — primary
- XIAOMI_API_KEY   — fallback (optional; being retired as the token-plan expires;
                     if unset, the Xiaomi fallback is skipped)

Notes:
- system is a TOP-LEVEL Anthropic param (not a message role) — we lift it out.
- thinking: enabled by default (better prose quality). For structured JSON
  extraction pass thinking_disabled=True — reasoning budget competing with the
  output cap truncates JSON, and a deterministic extraction wants thinking off.
- json_response: Anthropic has no response_format param, and mimo ignores an
  assistant "{" prefill (it re-opens a ```json fence instead). So we just instruct
  JSON in the prompt and pull the first balanced {…}/[…] out of the reply via
  _extract_json (fence- and stray-prose-tolerant).
- ANTHROPIC_VERSION header pinned to 2023-06-01 (what both vendors accept).

Usage:
    from clawock_kcnyu.automation.llm import chat
    reply = chat(system="...", user="...", max_tokens=32000)
"""
import json
import os
import re
import sys
import time

import requests

# Anthropic-protocol endpoints (base, no trailing /v1/messages — added per call).
DEFAULT_BASE = 'https://token-plan-cn.xiaomimimo.com/anthropic'
DEFAULT_MODEL = 'mimo-v2.5-pro'
MINIMAX_BASE = 'https://api.minimaxi.com/anthropic'
MINIMAX_MODEL = 'MiniMax-M3'
MINIMAX_MAX_TOKENS = 131072  # M3 maxOutput
XIAOMI_MAX_TOKENS = 32000  # mimo-v2.5-pro maxOutput — far below M3's
ANTHROPIC_VERSION = '2023-06-01'
TIMEOUT = 180  # 3 min per call
MAX_RETRIES = 3


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


def _call_provider(label, base_url, api_key, model, messages, max_tokens,
                   temperature, json_response, thinking, timeout=None):
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
        try:
            r = requests.post(f'{base_url}/v1/messages',
                              json=body, headers=headers, timeout=timeout)
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
                time.sleep(wait)
                continue
            else:
                last_err = f'HTTP {r.status_code}: {r.text[:300]}'
                print(f'  {label}: {last_err}', file=sys.stderr)
        except requests.Timeout:
            last_err = 'timeout after 180s'
            print(f'  {label}: {last_err} (attempt {attempt})', file=sys.stderr)
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            print(f'  {label}: {last_err}', file=sys.stderr)
        time.sleep(2 * attempt)
    raise RuntimeError(f'{label} failed after {MAX_RETRIES} attempts: {last_err}')


def chat(system: str = '', user: str = '', messages: list = None,
         max_tokens: int = 32000, temperature: float = 0.7,
         model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE,
         api_key: str = None, thinking_disabled: bool = False,
         json_response: bool = False, fallback: bool = True,
         timeout: int = None) -> str:
    """Call MiniMax M3; on total failure fall back to Xiaomi MiMo (both Anthropic
    Messages). Returns assistant content string, or raises if BOTH providers fail.
    Set fallback=False to use MiniMax only (no Xiaomi fallback).

    timeout: per-attempt seconds, default TIMEOUT (180). Big jobs need more: the
    daily brief prefills ~100KB of context and generates ~20K tokens with thinking
    on, which blew straight through 180s x3 on 2026-07-16 (callers see the retries
    as "timeout after 180s (attempt N)"). Raise it rather than shrink the prompt —
    trimming the brief's context is what made it blind to half the book.
    """
    if messages is None:
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        if user:
            messages.append({'role': 'user', 'content': user})

    thinking = {'type': 'disabled'} if thinking_disabled else {'type': 'enabled'}
    errors = []

    # ── Primary: MiniMax M3 (Anthropic Messages) ──
    # 2026-06-16, kcn: Xiaomi token-plan is expiring → MiniMax is now primary
    # everywhere. Xiaomi stays only as a last-resort fallback while its key still
    # works; once the token dies it is auto-skipped (no XIAOMI_API_KEY).
    mm_key = os.environ.get('MINIMAX_API_KEY')
    if mm_key:
        try:
            return _call_provider('minimax', MINIMAX_BASE, mm_key, MINIMAX_MODEL,
                                  messages, min(max_tokens, MINIMAX_MAX_TOKENS),
                                  temperature, json_response, thinking, timeout)
        except Exception as e:
            errors.append(f'minimax[{e}]')
            print('  ⚠️ minimax exhausted — falling back to Xiaomi MiMo', file=sys.stderr)
    else:
        errors.append('minimax[no MINIMAX_API_KEY]')

    # ── Fallback: Xiaomi MiMo (same Anthropic transport; key may be expired) ──
    xiaomi_key = api_key or os.environ.get('XIAOMI_API_KEY')
    if fallback and xiaomi_key:
        try:
            return _call_provider('xiaomi', base_url, xiaomi_key, model, messages,
                                  min(max_tokens, XIAOMI_MAX_TOKENS),
                                  temperature, json_response, thinking,
                                  timeout)
        except Exception as e:
            errors.append(f'xiaomi[{e}]')
    elif fallback and not xiaomi_key:
        errors.append('xiaomi[no XIAOMI_API_KEY]')

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
