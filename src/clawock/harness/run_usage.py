"""The usage footer a delivered cron card carries, read from the live runtime.

All three postflights call this at send time. It is deliberately total: a
missing runtime, an unreadable transcript, a manual or dry run, or an ambiguous
live task all return '' so the card goes out unchanged. It never prints a zero
as a stand-in for a number it could not read.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from clawock.harness import chat_card
from clawock.providers import openclaw
from clawock.workspace import workspace_root


def footer(*, paths=None, now_ms=None, job=None) -> str:
    """The two-line footer for the cron turn this process is serving, or ''.

    `job` names the scheduled job whose card is being sent. The postflights know
    it (brief/report from their workflow identity, intraday from the preflight
    heartbeat); naming it is what lets the reader find the live transcript while
    the runtime's session store still has no `sessionId` for it.
    """
    try:
        usage = openclaw.current_cron_run_usage(paths=paths, now_ms=now_ms, job=job)
    except Exception:
        return ''
    if job and (prompt_tokens := getattr(usage, 'prompt_tokens', None)) is not None:
        try:
            directory = workspace_root() / 'logs'
            directory.mkdir(parents=True, exist_ok=True)
            row = {
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'job': job,
                'model': usage.model,
                'provider': usage.provider,
                'prompt_tokens': prompt_tokens,
            }
            with (directory / 'cron-context-usage.log').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        except OSError:
            # Losing a measurement must never change card or delivery behavior.
            pass
    return chat_card.usage_footer(usage)


def append(text: str, *, paths=None, now_ms=None, job=None) -> str:
    """`text` with one blank line and the footer, or `text` untouched."""
    block = footer(paths=paths, now_ms=now_ms, job=job)
    return f'{text.rstrip()}\n\n{block}' if block else text
