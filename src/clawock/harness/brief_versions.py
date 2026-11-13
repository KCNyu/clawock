"""The brief's version chain: immutable reports behind one current pointer.

A daily brief used to be one in-place file: `memory/{date}-pre-open.md` was
re-rendered when a judgment was corrected, and the card delivered at 08:32 kept
linking to a page that now said something else.  #3105 made the *page* admit a
rewrite; that tells a reader the two disagree but does not preserve what the
card actually showed.  This module keeps every publishable render as an
immutable node and records which node the page (and therefore the card's link)
shows now.

The shape deliberately stops short of chat-demo's message tree.  A brief has one
linear lineage per day: a re-run either reproduces the current report (pure
retry) or appends a corrected version.  There is no "switch to another branch"
operation to represent, so there is no branch field, no parent tree and no UI.
Each node keeps the previous `current` as `parent` only to make the lineage
readable:

    memory/brief-versions/{date}/index.json
    memory/brief-versions/{date}/v1-3f2a9c1b.md
    memory/brief-versions/{date}/v2-8d1e0f2a.md

`index.json.current` names the version the page at `memory/{date}-pre-open.md`
must match.  `report_sha256` has always been computed with the revision banner
stripped (`brief_postflight.report_sha256`); a snapshot stores exactly that
text, so a digest in the delivery receipt and a snapshot can be compared
directly.  A version is content-addressed: re-rendering the same report reuses
its node instead of appending a duplicate, and a correction moves `current`
forward.  Reverting to older bytes moves `current` back to that node; nothing is
deleted.

Writers hold `safe_io.temp_dir_lock` across the read/modify/write, so two
postflights (for example a host retry racing the off-host fallback) cannot lose
one another's version.  The index is written after its immutable report.
`index.json` is the owner of "current"; a corrupt index raises rather than being
replaced, so a repair never silently forgets which delivery was bound to which
version.

The delivery receipt (`memory/.tmp/brief-sent-{date}.json`) binds the version
that actually went out with `brief_version`, `brief_version_path` and
`brief_version_sha256`; `report_sha256` stays for older readers.  A receipt from
before this module has only `report_sha256`, and `find_by_sha` lets postflight
bind it when that digest still names an archived version.  Postflight calls this
module after rendering and validation, and fails open: a version-store error is
reported and the card still goes out, because traceability must not cost the
brief.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clawock.safe_io import safe_write_json, safe_write_text, temp_dir_lock

HKT = timezone(timedelta(hours=8))

VERSION_ID_RE = re.compile(r'^v(\d+)-([0-9a-f]{8})$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
SCHEMA_VERSION = 1


class VersionStoreError(RuntimeError):
    """The version store cannot be read or written safely."""


def versions_dir(workspace, day):
    return Path(workspace) / 'memory' / 'brief-versions' / day


def index_path(workspace, day):
    return versions_dir(workspace, day) / 'index.json'


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _stamp(at):
    at = at or datetime.now(HKT)
    if at.tzinfo is None:
        at = at.replace(tzinfo=HKT)
    return at.astimezone(HKT).isoformat(timespec='seconds')


def _check_day(day):
    if not isinstance(day, str) or not DATE_RE.fullmatch(day):
        raise VersionStoreError(f'invalid brief date: {day!r}')


def _empty_index(day):
    return {
        'schema_version': SCHEMA_VERSION,
        'date': day,
        'current': None,
        'current_sha256': None,
        'updated_at': None,
        'versions': [],
    }


def _load_index(path, day):
    """Read the index, or return an empty one when it does not exist yet.

    A malformed or foreign index is an error, not an invitation to overwrite:
    the versions it lists are the only record of which report a delivered card
    showed.
    """
    try:
        raw = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return _empty_index(day)
    except OSError as exc:
        raise VersionStoreError(f'cannot read {path}: {exc}') from exc
    try:
        index = json.loads(raw)
    except ValueError as exc:
        raise VersionStoreError(f'cannot parse {path}: {exc}') from exc
    if not isinstance(index, dict):
        raise VersionStoreError(f'{path} is not a JSON object')
    if index.get('schema_version') != SCHEMA_VERSION:
        raise VersionStoreError(
            f'{path} has schema_version={index.get("schema_version")!r}, '
            f'expected {SCHEMA_VERSION}')
    if index.get('date') != day:
        raise VersionStoreError(f'{path} is for {index.get("date")!r}, not {day}')
    if not isinstance(index.get('versions'), list):
        raise VersionStoreError(f'{path} has no versions list')
    return index


def _row(index, version_id):
    return next(
        (row for row in index.get('versions') or []
         if isinstance(row, dict) and row.get('id') == version_id),
        None,
    )


def _public_row(row):
    return dict(row) if isinstance(row, dict) else None


def _write_index(path, index):
    safe_write_json(str(path), index)


def current(workspace, day):
    """The version row the page must match, or None before the first render."""
    _check_day(day)
    path = index_path(workspace, day)
    try:
        index = _load_index(path, day)
    except VersionStoreError:
        return None
    return _public_row(_row(index, index.get('current')))


def find_by_sha(workspace, day, sha256):
    """The archived version with this report digest, or None."""
    if not isinstance(sha256, str) or not sha256:
        return None
    _check_day(day)
    try:
        index = _load_index(index_path(workspace, day), day)
    except VersionStoreError:
        return None
    return _public_row(next(
        (row for row in index.get('versions') or []
         if isinstance(row, dict) and row.get('sha256') == sha256),
        None,
    ))


def load_report(workspace, day, version_id):
    """The immutable report text for `version_id`, or None if it is not there."""
    _check_day(day)
    if not isinstance(version_id, str) or not VERSION_ID_RE.fullmatch(version_id):
        return None
    path = versions_dir(workspace, day) / f'{version_id}.md'
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return None


def capture(workspace, day, text, *, generation_id=None, at=None):
    """Keep `text` as a version and make it current. Returns the version row.

    `text` must be the report as delivered — the revision banner is presentation
    owned by postflight, not part of a version.  Identical bytes reuse the
    existing node; only the pointer moves.
    """
    _check_day(day)
    if not isinstance(text, str) or not text:
        raise VersionStoreError('cannot version an empty report')
    directory = versions_dir(workspace, day)
    path = directory / 'index.json'
    sha = _digest(text)
    stamp = _stamp(at)
    with temp_dir_lock(str(path), 'briefversions'):
        index = _load_index(path, day)
        versions = index.setdefault('versions', [])
        existing = next(
            (row for row in versions
             if isinstance(row, dict) and row.get('sha256') == sha),
            None,
        )
        if existing is not None:
            if index.get('current') != existing.get('id'):
                index['current'] = existing.get('id')
                index['current_sha256'] = sha
                index['updated_at'] = stamp
                _write_index(path, index)
            return _public_row(existing)

        used = [row.get('seq') for row in versions
                if isinstance(row, dict) and isinstance(row.get('seq'), int)]
        seq = max(used, default=0) + 1
        version_id = f'v{seq}-{sha[:8]}'
        filename = f'{version_id}.md'
        target = directory / filename
        # Write the report before the index names it.  A half-created version is
        # harmless and repairable; an index row pointing at no file is not.
        if target.exists():
            try:
                same = target.read_text(encoding='utf-8')
            except OSError as exc:
                raise VersionStoreError(f'cannot read {target}: {exc}') from exc
            if same != text:
                raise VersionStoreError(
                    f'{target} already exists with different content; '
                    'refusing to overwrite an immutable version')
        else:
            safe_write_text(str(target), text)

        previous = index.get('current')
        row = {
            'id': version_id,
            'seq': seq,
            'sha256': sha,
            'bytes': len(text.encode('utf-8')),
            'file': filename,
            'path': f'memory/brief-versions/{day}/{filename}',
            'created_at': stamp,
            'generation_id': generation_id,
            'parent': previous if isinstance(previous, str) else None,
        }
        versions.append(row)
        index['current'] = version_id
        index['current_sha256'] = sha
        index['updated_at'] = stamp
        _write_index(path, index)
        return _public_row(row)


def record_delivery(workspace, day, version_id, *, at=None, channels=None,
                    receipt_name=None):
    """Bind a delivered card to the version it showed. Returns the row or None.

    Called after a send returned success on at least one channel.  A missing
    version is reported by returning None; the caller must not turn that into a
    delivery failure.
    """
    _check_day(day)
    if not isinstance(version_id, str) or not VERSION_ID_RE.fullmatch(version_id):
        return None
    path = index_path(workspace, day)
    stamp = _stamp(at)
    with temp_dir_lock(str(path), 'briefversions'):
        try:
            index = _load_index(path, day)
        except VersionStoreError:
            return None
        row = _row(index, version_id)
        if row is None:
            return None
        row['delivery'] = {
            'at': stamp,
            'channels': {
                name: bool(ok) for name, ok in (channels or {}).items()
            },
            **({'receipt': receipt_name} if receipt_name else {}),
        }
        index['updated_at'] = stamp
        _write_index(path, index)
        return _public_row(row)


def archive_url(workspace, row):
    """A public link to an archived version, when the desk declares its repo.

    Pages serves the live page only; the version directory is committed to the
    repository, so the honest link is the repository's blob view.  A workspace
    without `repo_url` gets no link rather than a broken or invented one.
    """
    if not isinstance(row, dict) or not row.get('path'):
        return ''
    try:
        contract = json.loads(
            (Path(workspace) / 'config' / 'pages-public.json').read_text(encoding='utf-8'))
        repo = str(contract.get('repo_url') or '').strip().rstrip('/')
    except (OSError, ValueError, AttributeError):
        repo = ''
    if not repo:
        return ''
    branch = str(contract.get('repo_branch') or 'master').strip()
    return f"{repo}/blob/{branch}/{row['path']}"
