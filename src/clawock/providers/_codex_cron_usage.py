"""Read Codex app-server usage linked to one OpenClaw cron transcript."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID


def _records(path):
    try:
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def record_timestamp(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _rollout(home, thread_id, started):
    try:
        thread = UUID(thread_id)
        # Codex uses UUIDv7. A resumed thread's file is under its creation
        # date, and the Codex server's local date can differ from ours.
        created = (thread.int >> 80) / 1000 if thread.version == 7 else started
        day = datetime.fromtimestamp(created, timezone.utc).date()
    except (AttributeError, ValueError, TypeError, OverflowError, OSError):
        return None
    for offset in (0, -1, 1):
        directory = home / 'sessions' / (day + timedelta(days=offset)).strftime('%Y/%m/%d')
        for path in directory.glob(f'rollout-*-{thread}.jsonl'):
            header = next(_records(path), {})
            payload = header.get('payload')
            if (header.get('type') == 'session_meta' and isinstance(payload, dict)
                    and payload.get('id') == thread_id):
                return path
    return None


_BUCKETS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens')


def _usage_buckets(record):
    if not isinstance(record, dict):
        return None
    values = tuple(record.get(key, 0 if key == 'cache_write_input_tokens' else None)
                   for key in _BUCKETS)
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return values if values[1] <= values[0] else None


@dataclass(frozen=True)
class CodexTurnUsage:
    provider: str
    model: str
    started: float
    # Native input includes cache reads. Keep the split until pricing.
    buckets: tuple[int, int, int, int] | None
    prompt_tokens: int | None


def _turn_usage(path, turn_id, model):
    active = confirmed = False
    baseline = total = last = None
    for record in _records(path):
        payload = record.get('payload')
        if not isinstance(payload, dict):
            continue
        kind = payload.get('type')
        if kind == 'task_started':
            if active:
                break
            active = payload.get('turn_id') == turn_id
        elif active and kind == 'task_complete':
            break
        elif active and record.get('type') == 'turn_context':
            if payload.get('turn_id') == turn_id:
                confirmed = payload.get('model') == model
                if not confirmed:
                    return None, None
        elif active and confirmed and kind == 'token_count':
            info = payload.get('info')
            if not isinstance(info, dict):
                continue
            new_total = _usage_buckets(info.get('total_token_usage'))
            new_last = _usage_buckets(info.get('last_token_usage'))
            if new_total is None or new_last is None:
                return None, None
            if baseline is None:
                baseline = tuple(a - b for a, b in zip(new_total, new_last, strict=True))
            if (min(baseline) < 0 or total is not None
                    and any(a < b for a, b in zip(new_total, total, strict=True))):
                return None, None
            total, last = new_total, new_last
    if total is None or baseline is None or last is None:
        return None, None
    return tuple(a - b for a, b in zip(total, baseline, strict=True)), last[0]


def read_codex_turns(transcript: Path, config: dict) -> list[CodexTurnUsage]:
    """Follow only the thread/turn IDs emitted for this exact session."""
    app_server = (config.get('plugins', {}).get('entries', {}).get('codex', {})
                  .get('config', {}).get('appServer', {}))
    if app_server.get('homeScope') == 'user':
        home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    else:
        home = transcript.parent.parent / 'agent' / 'codex-home'
    trajectory = transcript.with_suffix('.trajectory.jsonl')
    turns = {}
    for event in _records(trajectory):
        if (event.get('traceSchema') != 'openclaw-trajectory'
                or event.get('source') != 'runtime'
                or event.get('sessionId') != transcript.stem
                or event.get('type') != 'prompt.submitted'):
            continue
        data = event.get('data')
        if not isinstance(data, dict):
            continue
        thread_id, turn_id = data.get('threadId'), data.get('turnId')
        provider, model = event.get('provider'), event.get('modelId')
        started = record_timestamp(event.get('ts'))
        if not (started and all(isinstance(v, str) and v
                                for v in (thread_id, turn_id, provider, model))):
            continue
        if (thread_id, turn_id) in turns:
            continue
        rollout = _rollout(home, thread_id, started)
        buckets, prompt = _turn_usage(rollout, turn_id, model) if rollout else (None, None)
        turns[thread_id, turn_id] = CodexTurnUsage(provider, model, started, buckets, prompt)
    return list(turns.values())
