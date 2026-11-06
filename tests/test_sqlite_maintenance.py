"""Focused checks for the host SQLite maintenance script.

The live run stops the gateway, so these tests exercise the database steps on
throwaway databases and the read-only CLI through module globals. They never
touch the live index.
"""
import importlib.util
import json
import sqlite3
from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'sqlite_maintenance', ROOT / 'ops' / 'host' / 'sqlite_maintenance.py')
maintenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maintenance)


def _make_db(path: Path, *, rows: int = 600, delete: int = 500) -> None:
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE chunks (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
    conn.executemany(
        'INSERT INTO chunks (body) VALUES (?)',
        [(('x' * 800),) for _ in range(rows)],
    )
    conn.execute(f'DELETE FROM chunks WHERE id <= {delete}')
    conn.commit()
    conn.close()


def test_vacuum_switches_auto_vacuum_and_reclaims_the_freelist(tmp_path):
    path = tmp_path / 'index.sqlite'
    _make_db(path)
    before = maintenance.check_one(path)
    assert before['auto_vacuum'] == 0
    assert before['freelist_count'] > 0

    result = maintenance.maintain_db(path, mode='vacuum', full=False)

    assert result['quick_check'] == 'ok'
    assert result['integrity_check'] == 'ok'
    assert result['after']['auto_vacuum'] == 2
    assert result['after']['freelist_count'] == 0
    assert result['after']['sizes']['db'] <= before['sizes']['db']
    assert result['steps'][0]['checkpoint_before']['busy'] == 0


def test_second_run_uses_incremental_vacuum(tmp_path):
    path = tmp_path / 'index.sqlite'
    _make_db(path)
    maintenance.maintain_db(path, mode='vacuum', full=False)

    conn = sqlite3.connect(path)
    conn.execute('DELETE FROM chunks WHERE id <= 90')
    conn.commit()
    conn.close()

    result = maintenance.maintain_db(path, mode='vacuum', full=False)

    assert result['after']['auto_vacuum'] == 2
    assert result['steps'][1]['action'] == 'incremental_vacuum'


def test_backup_restore_round_trip(tmp_path):
    path = tmp_path / 'index.sqlite'
    _make_db(path, rows=40, delete=0)
    backup = maintenance.backup_db(path, tmp_path / 'backup' / 'index.sqlite')
    assert Path(backup['path']).exists()
    assert backup['sha256']

    conn = sqlite3.connect(path)
    conn.execute('DELETE FROM chunks')
    conn.commit()
    conn.close()

    maintenance.restore_db(backup)

    conn = sqlite3.connect(path)
    assert conn.execute('SELECT COUNT(*) FROM chunks').fetchone()[0] == 40
    conn.close()


def test_state_auto_vacuum_off_alone_is_not_a_recommendation(tmp_path, monkeypatch):
    index = tmp_path / 'index.sqlite'
    state = tmp_path / 'state.sqlite'
    _make_db(index, rows=20, delete=0)
    _make_db(state, rows=20, delete=0)
    monkeypatch.setattr(maintenance, 'STATE_DB', state)

    # The main index has auto_vacuum=0, so it is a candidate; the state store
    # is checkpoint-only and has no freelist/WAL pressure, so it is not.
    assert maintenance.check_one(index)['recommended'] is True
    assert maintenance.check_one(state)['recommended'] is False


def test_check_cli_is_read_only_and_reports_space(tmp_path, monkeypatch, capsys):
    index = tmp_path / 'index.sqlite'
    state = tmp_path / 'state.sqlite'
    _make_db(index, rows=20, delete=0)
    _make_db(state, rows=20, delete=0)
    monkeypatch.setattr(maintenance, 'MAIN_DB', index)
    monkeypatch.setattr(maintenance, 'STATE_DB', state)

    assert maintenance.main(['--check', '--json']) == 0
    report = json.loads(capsys.readouterr().out)

    assert [item['path'] for item in report['databases']] == [str(index), str(state)]
    assert report['space_ok'] is True
    assert report['databases'][0]['journal_mode'] == 'wal'
    # --check must not change the auto_vacuum mode.
    conn = sqlite3.connect(index)
    assert conn.execute('PRAGMA auto_vacuum').fetchone()[0] == 0
    conn.close()
