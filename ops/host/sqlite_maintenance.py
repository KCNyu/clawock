#!/usr/bin/env python3
"""Offline maintenance for OpenClaw's SQLite memory index and state store.

The script is deliberately host-local: it knows the live OpenClaw paths, the
systemd user unit, and the gateway health endpoint. It does not implement any
portfolio or workflow semantics.

What `--apply` does, in order:

1. reads the before image (`--check` logic) and checks free disk space;
2. stops `openclaw-gateway.service` and waits for its readers to disappear;
3. takes a consistent SQLite backup of both databases;
4. runs `wal_checkpoint(TRUNCATE)`;
5. on the memory index only: `PRAGMA auto_vacuum=INCREMENTAL` + `VACUUM`
   (or `PRAGMA incremental_vacuum` on later runs, when the mode is already set);
6. runs `quick_check` (and `integrity_check` after a full VACUUM);
7. records the after image and writes a JSON report;
8. starts the gateway and waits for `/health`.

Any database error after the backup restores both databases from it and starts
the gateway again. `--check` is read-only and needs no outage.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAIN_DB = Path('/root/.openclaw/agents/main/agent/openclaw-agent.sqlite')
STATE_DB = Path('/root/.openclaw/state/openclaw.sqlite')
BACKUP_ROOT = Path('/root/backups/openclaw-sqlite')
REPORT_DIR = Path('/root/logs/sqlite-maintenance')
LOCK_PATH = Path('/root/.openclaw/state/sqlite-maintenance.lock')
GATEWAY_UNIT = 'openclaw-gateway.service'
HEALTH_URL = 'http://127.0.0.1:18789/health'
DB_SUFFIXES = ('-wal', '-shm', '-journal')
MIB = 1024 * 1024


class MaintenanceError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def human(n: int | float | None) -> str:
    if n is None:
        return '-'
    n = float(n)
    if abs(n) >= 1024 ** 3:
        return f'{n / 1024 ** 3:.2f}G'
    if abs(n) >= MIB:
        return f'{n / MIB:.1f}M'
    if abs(n) >= 1024:
        return f'{n / 1024:.1f}K'
    return f'{n:.0f}B'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * MIB), b''):
            digest.update(chunk)
    return digest.hexdigest()


def connect(path: Path, *, read_only: bool = False, timeout: float = 10.0) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=timeout)
    else:
        conn = sqlite3.connect(path, timeout=timeout, isolation_level=None)
    conn.execute(f'PRAGMA busy_timeout={int(timeout * 1000)}')
    return conn


def pragma(conn: sqlite3.Connection, name: str):
    row = conn.execute(f'PRAGMA {name}').fetchone()
    return row[0] if row else None


def check_messages(conn: sqlite3.Connection, name: str) -> list[str]:
    rows = [str(row[0]) for row in conn.execute(f'PRAGMA {name}').fetchall()]
    return [row for row in rows if row.lower() != 'ok']


def file_sizes(path: Path) -> dict:
    out = {'db': path.stat().st_size if path.exists() else 0}
    for suffix in DB_SUFFIXES:
        side = path.with_name(path.name + suffix)
        out[suffix.lstrip('-')] = side.stat().st_size if side.exists() else 0
    return out


def process_name(pid: str) -> str:
    try:
        comm = Path(f'/proc/{pid}/comm').read_text().strip()
    except OSError:
        return '?'
    try:
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode('utf-8', 'replace')
    except OSError:
        cmd = ''
    return f'{comm} ({cmd[:100].strip()})' if cmd else comm


def open_handles(paths: list[Path]) -> list[dict]:
    """Processes other than this one holding any of the database files open."""
    wanted = set()
    for path in paths:
        wanted.add(str(path))
        for suffix in DB_SUFFIXES:
            wanted.add(str(path.with_name(path.name + suffix)))
    handles: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        fd_dir = entry / 'fd'
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target in wanted and (int(entry.name), target) not in seen:
                seen.add((int(entry.name), target))
                handles.append({
                    'pid': int(entry.name),
                    'name': process_name(entry.name),
                    'path': target,
                })
    return handles


def systemctl(action: str, *, timeout: float = 180.0) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    uid = os.getuid()
    env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{uid}')
    env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{uid}/bus')
    return subprocess.run(
        ['systemctl', '--user', action, GATEWAY_UNIT],
        env=env, capture_output=True, text=True, timeout=timeout,
    )


def gateway_active() -> bool:
    result = systemctl('is-active', timeout=15)
    return result.returncode == 0 and result.stdout.strip() == 'active'


def wait_gateway(active: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gateway_active() is active:
            return True
        time.sleep(0.5)
    return False


def health_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
            payload = json.loads(response.read().decode('utf-8'))
        return payload.get('ok') is True
    except (OSError, ValueError):
        return False


def wait_health(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_ok():
            return True
        time.sleep(1)
    return False


def stop_gateway() -> None:
    if not gateway_active():
        return
    result = systemctl('stop', timeout=180)
    if result.returncode != 0:
        raise MaintenanceError(f'systemctl stop failed: {result.stderr.strip()}')
    if not wait_gateway(False, 150):
        raise MaintenanceError('gateway did not stop within 150s')


def start_gateway() -> dict:
    result = systemctl('start', timeout=60)
    active = wait_gateway(True, 60)
    healthy = wait_health(90) if active else False
    return {
        'start_rc': result.returncode,
        'active': active,
        'health': healthy,
        'stderr': result.stderr.strip(),
    }


def wait_no_handles(paths: list[Path], timeout: float = 30.0) -> list[dict]:
    """Wait for external handles to close; return whatever is still open."""
    deadline = time.monotonic() + timeout
    while True:
        handles = open_handles(paths)
        if not handles or time.monotonic() >= deadline:
            return handles
        time.sleep(0.5)


def check_one(path: Path) -> dict:
    if not path.exists():
        raise MaintenanceError(f'missing database: {path}')
    conn = connect(path, read_only=True)
    try:
        sizes = file_sizes(path)
        info = {
            'path': str(path),
            'sizes': sizes,
            'page_size': pragma(conn, 'page_size'),
            'page_count': pragma(conn, 'page_count'),
            'freelist_count': pragma(conn, 'freelist_count'),
            'auto_vacuum': pragma(conn, 'auto_vacuum'),
            'journal_mode': pragma(conn, 'journal_mode'),
            'wal_autocheckpoint': pragma(conn, 'wal_autocheckpoint'),
            'journal_size_limit': pragma(conn, 'journal_size_limit'),
            'quick_check': check_messages(conn, 'quick_check'),
        }
        info['freelist_bytes'] = (info['freelist_count'] or 0) * (info['page_size'] or 0)
        info['open_handles'] = open_handles([path])
        usage = shutil.disk_usage(path.parent)
        info['disk_free'] = usage.free
        info['vacuum_temp_bytes'] = sizes['db'] * 2
        info['space_ok'] = usage.free >= sizes['db'] * 3 + 256 * MIB
        # The state store is checkpointed only; its auto_vacuum=0 is a
        # deliberate choice (12 free pages are not worth a full rewrite), so
        # it must not keep --check saying "maintenance recommended" forever.
        info['recommended'] = bool(
            (info['freelist_bytes'] or 0) > 8 * MIB
            or sizes['wal'] > 32 * MIB
            or (path != STATE_DB and info['auto_vacuum'] != 2)
        )
        return info
    finally:
        conn.close()


def collect_check(paths: list[Path]) -> dict:
    databases = [check_one(path) for path in paths]
    return {
        'checked_at': now(),
        'databases': databases,
        'open_handles': [h for db in databases for h in db['open_handles']],
        'space_ok': all(db['space_ok'] for db in databases),
        'recommended': any(db['recommended'] for db in databases),
    }


def print_check(report: dict) -> None:
    print(f"SQLite maintenance check · {report['checked_at']}")
    for db in report['databases']:
        print(f"\n{db['path']}")
        print(f"  size          {human(db['sizes']['db'])}  ({db['page_count']} pages × {db['page_size']}B)")
        print(f"  wal / shm     {human(db['sizes']['wal'])} / {human(db['sizes']['shm'])}")
        print(f"  freelist      {db['freelist_count']} pages = {human(db['freelist_bytes'])}")
        print(f"  auto_vacuum   {db['auto_vacuum']}  (0=OFF, 1=FULL, 2=INCREMENTAL)")
        print(f"  journal_mode  {db['journal_mode']}  wal_autocheckpoint={db['wal_autocheckpoint']}  "
              f"journal_size_limit={db['journal_size_limit']}")
        print(f"  quick_check   {'ok' if not db['quick_check'] else db['quick_check'][:3]}")
        if db['open_handles']:
            names = ', '.join(f"{h['pid']} {h['name']}" for h in db['open_handles'][:5])
            print(f"  open handles  {len(db['open_handles'])}: {names}")
    print(f"\ndisk free       {human(report['databases'][0]['disk_free'])}")
    print(f"space for run   {'ok' if report['space_ok'] else 'NOT ENOUGH'}")
    print(f"maintenance     {'recommended' if report['recommended'] else 'not needed now'}")


def backup_db(source: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    src = connect(source, read_only=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst, pages=512, sleep=0.01)
        dst.execute('PRAGMA journal_mode=DELETE')
        dst.commit()
        errors = check_messages(dst, 'quick_check')
        if errors:
            raise MaintenanceError(f'backup quick_check failed for {source}: {errors[:3]}')
        page_count = pragma(dst, 'page_count')
    finally:
        dst.close()
        src.close()
    os.chmod(destination, 0o600)
    return {
        'source': str(source),
        'path': str(destination),
        'bytes': destination.stat().st_size,
        'page_count': page_count,
        'sha256': sha256_file(destination),
    }


def checkpoint(conn: sqlite3.Connection, label: str) -> dict:
    busy, log_pages, checkpointed = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
    if busy:
        raise MaintenanceError(
            f'{label}: wal_checkpoint(TRUNCATE) busy={busy}; a reader still holds a snapshot'
        )
    return {'busy': busy, 'log_pages': log_pages, 'checkpointed_pages': checkpointed}


def vacuum_or_incremental(conn: sqlite3.Connection, label: str, *, full: bool) -> dict:
    before_mode = pragma(conn, 'auto_vacuum')
    before_pages = pragma(conn, 'page_count')
    before_free = pragma(conn, 'freelist_count')
    action = 'incremental_vacuum'
    if full or before_mode != 2:
        conn.execute('PRAGMA auto_vacuum=INCREMENTAL')
        conn.execute('VACUUM')
        action = 'auto_vacuum=INCREMENTAL + VACUUM'
    else:
        conn.execute('PRAGMA incremental_vacuum')
    return {
        'action': action,
        'auto_vacuum_before': before_mode,
        'auto_vacuum_after': pragma(conn, 'auto_vacuum'),
        'page_count_before': before_pages,
        'page_count_after': pragma(conn, 'page_count'),
        'freelist_before': before_free,
        'freelist_after': pragma(conn, 'freelist_count'),
    }


def maintain_db(path: Path, *, mode: str, full: bool) -> dict:
    label = path.name
    conn = connect(path)
    try:
        before = check_one_locked(conn, path)
        result = {'path': str(path), 'before': before, 'steps': []}
        result['steps'].append({'checkpoint_before': checkpoint(conn, label)})
        if mode == 'vacuum':
            result['steps'].append(vacuum_or_incremental(conn, label, full=full))
            result['steps'].append({'checkpoint_after': checkpoint(conn, label)})
        quick = check_messages(conn, 'quick_check')
        integrity = check_messages(conn, 'integrity_check') if mode == 'vacuum' else []
        if quick or integrity:
            raise MaintenanceError(f'{label}: integrity failure quick={quick[:3]} full={integrity[:3]}')
        result['quick_check'] = 'ok'
        result['integrity_check'] = 'ok' if mode == 'vacuum' else 'skipped'
        result['after'] = check_one_locked(conn, path)
        return result
    finally:
        conn.close()


def check_one_locked(conn: sqlite3.Connection, path: Path) -> dict:
    sizes = file_sizes(path)
    page_size = pragma(conn, 'page_size')
    freelist = pragma(conn, 'freelist_count')
    return {
        'sizes': sizes,
        'page_size': page_size,
        'page_count': pragma(conn, 'page_count'),
        'freelist_count': freelist,
        'freelist_bytes': (freelist or 0) * (page_size or 0),
        'auto_vacuum': pragma(conn, 'auto_vacuum'),
        'journal_mode': pragma(conn, 'journal_mode'),
        'wal_autocheckpoint': pragma(conn, 'wal_autocheckpoint'),
        'journal_size_limit': pragma(conn, 'journal_size_limit'),
    }


def restore_db(backup: dict) -> None:
    source = Path(backup['path'])
    target = Path(backup['source'])
    if not source.exists():
        raise MaintenanceError(f'missing backup {source}')
    if sha256_file(source) != backup['sha256']:
        raise MaintenanceError(f'backup checksum mismatch: {source}')
    for suffix in DB_SUFFIXES:
        side = target.with_name(target.name + suffix)
        if side.exists():
            side.unlink()
    shutil.copy2(source, target)
    os.chmod(target, 0o600)
    conn = connect(target, read_only=True)
    try:
        errors = check_messages(conn, 'quick_check')
        if errors:
            raise MaintenanceError(f'restored database failed quick_check: {errors[:3]}')
    finally:
        conn.close()


def write_report(report: dict, stamp: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f'{stamp}.json'
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)
    return path


def print_summary(report: dict) -> None:
    print(f"SQLite maintenance · {report['result']} · {report['finished_at']}")
    for item in report.get('databases', []):
        if item.get('skipped'):
            print(f"\n{item['path']}")
            print(f"  skipped       {item['skipped']}")
            continue
        before, after = item['before'], item['after']
        print(f"\n{item['path']}")
        print(f"  file          {human(before['sizes']['db'])} -> {human(after['sizes']['db'])} "
              f"({human(after['sizes']['db'] - before['sizes']['db'])})")
        print(f"  wal           {human(before['sizes']['wal'])} -> {human(after['sizes']['wal'])}")
        print(f"  freelist      {before['freelist_count']} -> {after['freelist_count']} pages "
              f"({human(before['freelist_bytes'])} -> {human(after['freelist_bytes'])})")
        print(f"  auto_vacuum   {before['auto_vacuum']} -> {after['auto_vacuum']}")
        print(f"  quick_check   {item.get('quick_check', '-')}  integrity={item.get('integrity_check', '-')}")
        for step in item.get('steps', []):
            for name, value in step.items():
                print(f"  {name}: {value}")
    if 'backup_dir' in report:
        print(f"\nbackup          {report['backup_dir']}")
    if 'disk_free_after' in report:
        print(f"disk free       {human(report['disk_free_after'])}")
    if report.get('error'):
        print(f"error           {report['error']}")


def run_check(paths: list[Path], as_json: bool) -> int:
    report = collect_check(paths)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_check(report)
    return 0


def run_apply(paths: list[Path], *, full: bool, no_restart: bool, as_json: bool) -> int:
    if os.geteuid() != 0:
        print('sqlite maintenance must run as root', file=sys.stderr)
        return 2
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_PATH.open('w')
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('another sqlite maintenance run holds the lock', file=sys.stderr)
        return 3

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report: dict = {
        'schema': 1,
        'started_at': now(),
        'result': 'failed',
        'gateway_was_active': gateway_active(),
        'databases': [],
    }
    backups: list[dict] = []
    backup_dir = BACKUP_ROOT / stamp
    gateway_stopped = False
    try:
        before = collect_check(paths)
        report['check_before'] = before
        if not before['space_ok']:
            raise MaintenanceError(
                f"not enough disk for a safe run: free={human(before['databases'][0]['disk_free'])}"
            )
        stop_gateway()
        gateway_stopped = True
        main_handles = wait_no_handles([MAIN_DB], 30)
        if main_handles:
            detail = '; '.join(
                f"pid {h['pid']} {h['name']} -> {h['path']}" for h in main_handles[:8])
            raise MaintenanceError(f'memory index still open after gateway stop: {detail}')
        state_handles = wait_no_handles([STATE_DB], 10)
        report['gateway_stopped_at'] = now()

        backup_dir.mkdir(parents=True, exist_ok=True)
        for path in paths:
            backups.append(backup_db(path, backup_dir / path.name))
        report['backups'] = backups
        report['backup_dir'] = str(backup_dir)
        (backup_dir / 'manifest.json').write_text(json.dumps({
            'schema': 1,
            'created_at': now(),
            'before': before,
            'backups': backups,
            'report_stamp': stamp,
        }, ensure_ascii=False, indent=2) + '\n')

        for path in paths:
            if path == STATE_DB and state_handles:
                report['databases'].append({
                    'path': str(path),
                    'skipped': 'readers still hold the state database',
                    'open_handles': state_handles,
                })
                continue
            mode = 'vacuum' if path == MAIN_DB else 'checkpoint'
            report['databases'].append(maintain_db(path, mode=mode, full=full))
        if state_handles:
            report['state_skipped'] = True

        report['disk_free_after'] = shutil.disk_usage(MAIN_DB.parent).free
        report['result'] = 'ok'
        if no_restart:
            report['gateway'] = {'started': False, 'reason': '--no-restart'}
        else:
            report['gateway'] = start_gateway()
            if not (report['gateway']['active'] and report['gateway']['health']):
                raise MaintenanceError(f"gateway did not come back healthy: {report['gateway']}")
        report['finished_at'] = now()
        report_path = write_report(report, stamp)
        report['report_path'] = str(report_path)
        if as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_summary(report)
            print(f"report          {report_path}")
        return 0
    except Exception as exc:  # noqa: BLE001 - report every failure, then roll back
        report['error'] = f'{type(exc).__name__}: {exc}'
        report['failed_at'] = now()
        if backups:
            try:
                # A late failure (gateway start/health) leaves the gateway
                # running; never copy a database underneath an open handle.
                if gateway_active():
                    stop_gateway()
                for backup in backups:
                    restore_db(backup)
                report['rollback'] = 'restored both databases from backup'
            except Exception as rollback_exc:  # noqa: BLE001
                report['rollback'] = f'FAILED: {type(rollback_exc).__name__}: {rollback_exc}'
        else:
            report['rollback'] = 'not needed (no backup taken)'
        if gateway_stopped:
            try:
                report['gateway'] = start_gateway()
            except Exception as start_exc:  # noqa: BLE001
                report['gateway'] = {'active': False, 'health': False, 'error': str(start_exc)}
        report['finished_at'] = now()
        try:
            report_path = write_report(report, stamp)
            report['report_path'] = str(report_path)
        except OSError:
            report_path = None
        if as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_summary(report)
            if report_path:
                print(f"report          {report_path}")
        return 1
    finally:
        fcntl.flock(lock_handle, fcntl.LOCK_UN)
        lock_handle.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='read-only measurement; no outage')
    mode.add_argument('--apply', action='store_true', help='stop gateway, back up, checkpoint, vacuum, verify')
    parser.add_argument('--json', action='store_true', help='machine-readable output')
    parser.add_argument('--full', action='store_true', help='force VACUUM even when auto_vacuum is already INCREMENTAL')
    parser.add_argument('--no-restart', action='store_true', help='leave the gateway stopped after a successful run')
    args = parser.parse_args(argv)

    paths = [MAIN_DB, STATE_DB]
    if args.check:
        return run_check(paths, args.json)
    return run_apply(paths, full=args.full, no_restart=args.no_restart, as_json=args.json)


if __name__ == '__main__':
    raise SystemExit(main())
