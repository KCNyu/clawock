"""The usage footer on delivered cron cards.

Covers the two halves separately: the formatter that has to match the approved
two-line reply footer, and the reader that takes a live cron turn's model/cost
out of the runtime's own task/session/transcript records. The card-level tests
then pin that a footer rides at the foot and that an absent one changes nothing.
"""
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from clawock.harness import brief_card, chat_card
from clawock.harness import run_usage
from clawock.providers import openclaw as provider

HKT = ZoneInfo('Asia/Hong_Kong')
NOW = int(datetime(2026, 10, 31, 12, 0, tzinfo=HKT).timestamp() * 1000)


def _paths(tmp_path):
    return provider.OpenClawPaths(
        binary='/opt/openclaw/bin/openclaw',
        home=tmp_path / 'openclaw',
        install_dir=None,
    )


def _state_db(paths):
    paths.state_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(paths.state_db)
    conn.executescript(
        """
        CREATE TABLE cron_jobs (
            store_key TEXT NOT NULL, job_id TEXT NOT NULL, job_json TEXT NOT NULL,
            state_json TEXT NOT NULL, sort_order INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE cron_run_logs (
            store_key TEXT NOT NULL, job_id TEXT NOT NULL, seq INTEGER NOT NULL,
            ts INTEGER NOT NULL, entry_json TEXT NOT NULL
        );
        CREATE TABLE task_runs (
            task_id TEXT, runtime TEXT, status TEXT, child_session_key TEXT,
            source_id TEXT, started_at INTEGER, last_event_at INTEGER,
            created_at INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO cron_jobs VALUES (?, ?, ?, ?, ?, ?)",
        ('store', 'job-1', '{}', '{}', 0, 1),
    )
    return conn


def _write_sessions(paths, *, session_id='sess-now', model='MiniMax-M3.1-Flash',
                    provider_id='minimax', context_tokens=None):
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)
    entry = {'sessionId': session_id, 'model': model, 'modelProvider': provider_id}
    if context_tokens is not None:
        entry['contextTokens'] = context_tokens
    (paths.sessions_dir / 'sessions.json').write_text(json.dumps({
        'agent:main:cron:job-1': entry,
    }))


def _write_transcript(paths, session_id, messages):
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({'type': 'session', 'id': session_id})]
    lines += [json.dumps({'type': 'message', 'message': message}) for message in messages]
    (paths.sessions_dir / f'{session_id}.jsonl').write_text('\n'.join(lines) + '\n')


def _assistant(*, model='MiniMax-M3.1-Flash', provider_id='minimax', input_tokens=0,
               output_tokens=0, cache_read=0, cache_write=0, total_tokens=0,
               cost=None):
    usage = {
        'input': input_tokens, 'output': output_tokens,
        'cacheRead': cache_read, 'cacheWrite': cache_write,
        'totalTokens': total_tokens,
    }
    if cost is not None:
        usage['cost'] = {
            'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0,
            'total': cost,
        }
    return {
        'role': 'assistant', 'model': model, 'provider': provider_id,
        'usage': usage,
    }


def _running_task(conn, *, started_at=NOW - 60_000):
    conn.execute(
        "INSERT INTO task_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('task-1', 'cron', 'running', 'agent:main:cron:job-1', 'job-1',
         started_at, started_at, started_at),
    )
    conn.commit()


# ── formatter ────────────────────────────────────────────────────────────────

def test_footer_matches_the_two_line_reply_footer():
    block = chat_card.usage_footer(
        model='deepseek-flash', context_pct=27, turn_usd=0.0071,
        day_usd=2.81, cache_hit_pct=97)
    assert block == (
        '```text\n'
        'deepseek-flash  [██▊░░░░░░░] 27%\n'
        '↑0.0071$  Σ2.810$  hit 97%\n'
        '```'
    )


def test_footer_omits_pieces_the_runtime_could_not_prove():
    assert chat_card.usage_footer() == ''
    assert chat_card.usage_footer(model='deepseek-flash') == (
        '```text\ndeepseek-flash\n```')
    assert chat_card.usage_footer(
        model='deepseek-flash', turn_usd=None, day_usd=None, cache_hit_pct=None,
        context_pct=None) == '```text\ndeepseek-flash\n```'


def test_a_known_zero_stays_zero_but_a_missing_price_does_not():
    known_zero = chat_card.usage_footer(model='gpt-6-luna', turn_usd=0.0, day_usd=0.0)
    assert '↑0.0000$' in known_zero and 'Σ0.000$' in known_zero
    missing = chat_card.usage_footer(model='gpt-6-luna', turn_usd=None, day_usd=None)
    assert '↑' not in missing and 'Σ' not in missing


def test_meter_follows_the_template_width_and_partial_cell():
    assert chat_card.usage_meter(0) == '░░░░░░░░░░'
    assert chat_card.usage_meter(27) == '██▊░░░░░░░'
    assert chat_card.usage_meter(50) == '█████░░░░░'
    assert chat_card.usage_meter(100) == '██████████'
    assert chat_card.usage_meter(None) == ''


def test_append_adds_one_block_and_leaves_the_card_alone_without_one(monkeypatch):
    assert run_usage.append('card') == 'card'
    monkeypatch.setattr(run_usage, 'footer', lambda **_: '```text\nm\n```')
    assert run_usage.append('card\n') == 'card\n\n```text\nm\n```'


# ── live run reader ──────────────────────────────────────────────────────────

def test_current_run_reports_the_model_and_both_costs(tmp_path):
    paths = _paths(tmp_path)
    conn = _state_db(paths)
    _running_task(conn)
    _write_sessions(paths, context_tokens=1000)
    _write_transcript(paths, 'sess-now', [
        _assistant(cost=0.02, input_tokens=100, output_tokens=50,
                   cache_read=850, total_tokens=1000),
    ])
    _write_transcript(paths, 'sess-prev', [
        _assistant(cost=0.01, input_tokens=10, output_tokens=5,
                   cache_read=85, total_tokens=100),
    ])
    conn.execute(
        "INSERT INTO cron_run_logs VALUES (?, ?, ?, ?, ?)",
        ('store', 'job-1', 1, NOW - 3_600_000, json.dumps({
            'jobId': 'job-1', 'action': 'finished', 'status': 'ok',
            'runAtMs': NOW - 3_600_000, 'sessionId': 'sess-prev',
        })),
    )
    conn.commit()
    conn.close()

    usage = provider.current_cron_run_usage(paths=paths, now_ms=NOW)

    assert usage is not None
    assert usage.model == 'MiniMax-M3.1-Flash'
    assert usage.provider == 'minimax'
    assert usage.turn_usd == 0.02
    assert usage.day_usd == 0.03
    assert usage.cache_hit_pct == 89
    assert usage.context_pct == 100


def test_prior_run_without_a_price_makes_the_day_total_unknown(tmp_path):
    paths = _paths(tmp_path)
    conn = _state_db(paths)
    _running_task(conn)
    _write_sessions(paths, context_tokens=1000)
    _write_transcript(paths, 'sess-now', [_assistant(cost=0.02, input_tokens=100)])
    _write_transcript(paths, 'sess-prev', [_assistant(input_tokens=10)])
    conn.execute(
        "INSERT INTO cron_run_logs VALUES (?, ?, ?, ?, ?)",
        ('store', 'job-1', 1, NOW - 3_600_000, json.dumps({
            'action': 'finished', 'runAtMs': NOW - 3_600_000,
            'sessionId': 'sess-prev',
        })),
    )
    conn.commit()
    conn.close()

    usage = provider.current_cron_run_usage(paths=paths, now_ms=NOW)

    assert usage.turn_usd == 0.02
    assert usage.day_usd is None


def test_a_zero_priced_run_is_known_zero_not_missing(tmp_path):
    paths = _paths(tmp_path)
    conn = _state_db(paths)
    _running_task(conn)
    _write_sessions(paths, model='gpt-6-luna', provider_id='openai',
                    context_tokens=2000)
    _write_transcript(paths, 'sess-now', [
        _assistant(model='gpt-6-luna', provider_id='openai', cost=0,
                   input_tokens=100, output_tokens=50, cache_read=850,
                   total_tokens=1000),
    ])
    conn.commit()
    conn.close()

    usage = provider.current_cron_run_usage(paths=paths, now_ms=NOW)

    assert usage.model == 'gpt-6-luna'
    assert usage.turn_usd == 0.0
    assert usage.day_usd == 0.0
    assert usage.context_pct == 50


def test_context_window_falls_back_to_the_runtime_model_table(tmp_path):
    paths = _paths(tmp_path)
    conn = _state_db(paths)
    _running_task(conn)
    _write_sessions(paths, model='gpt-6-luna', provider_id='openai')
    paths.config_file.write_text(json.dumps({
        'models': {'providers': {'openai': {'models': [
            {'id': 'gpt-6-luna', 'contextWindow': 4000},
        ]}}},
    }))
    _write_transcript(paths, 'sess-now', [
        _assistant(model='gpt-6-luna', provider_id='openai', cost=0,
                   input_tokens=1000, total_tokens=1000),
    ])
    conn.commit()
    conn.close()

    usage = provider.current_cron_run_usage(paths=paths, now_ms=NOW)

    assert usage.context_pct == 25


def test_no_live_task_means_no_footer_data(tmp_path):
    paths = _paths(tmp_path)
    conn = _state_db(paths)
    conn.commit()
    conn.close()

    assert provider.current_cron_run_usage(paths=paths, now_ms=NOW) is None


def test_a_stale_running_row_does_not_hide_the_live_one(tmp_path):
    paths = _paths(tmp_path)
    conn = _state_db(paths)
    _running_task(conn)
    conn.execute(
        "INSERT INTO task_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('task-2', 'cron', 'running', 'agent:main:cron:job-2', 'job-2',
         NOW - 30_000, NOW - 30_000, NOW - 30_000),
    )
    _write_sessions(paths, context_tokens=1000)
    _write_transcript(paths, 'sess-now', [_assistant(cost=0.02, input_tokens=100)])
    conn.commit()
    conn.close()

    usage = provider.current_cron_run_usage(paths=paths, now_ms=NOW)

    assert usage is not None
    assert usage.model == 'MiniMax-M3.1-Flash'


def test_a_crashed_running_row_older_than_the_turn_budget_is_ignored(tmp_path):
    paths = _paths(tmp_path)
    conn = _state_db(paths)
    _running_task(conn, started_at=NOW - 2 * 60 * 60 * 1000)
    conn.commit()
    conn.close()

    assert provider.current_cron_run_usage(paths=paths, now_ms=NOW) is None


def test_missing_runtime_tables_are_quiet(tmp_path):
    paths = _paths(tmp_path)
    paths.state_db.parent.mkdir(parents=True)
    sqlite3.connect(paths.state_db).close()

    assert provider.current_cron_run_usage(paths=paths, now_ms=NOW) is None

# ── card composition ────────────────────────────────────────────────────────

def test_brief_card_puts_the_footer_at_its_foot(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_card, 'WS', tmp_path)
    (tmp_path / 'memory' / '.tmp').mkdir(parents=True)
    (tmp_path / 'memory' / '.tmp' / 'brief-card-2026-10-31.txt').write_text('**card**\n')
    footer = '```text\ndeepseek-flash  [██▊░░░░░░░] 27%\n↑0.0071$  Σ2.810$  hit 97%\n```'

    card = brief_card.build_brief_card('2026-10-31', decision_packet={}, footer=footer)

    assert card.startswith('**card**')
    assert card.endswith(footer)
    assert brief_card.build_brief_card(
        '2026-10-31', decision_packet={}, footer='') == card[: -len(footer) - 2]
