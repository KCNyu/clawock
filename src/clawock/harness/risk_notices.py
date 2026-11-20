"""Track which risk review states have reached a scheduled card."""
import json
import sys

from clawock.decision import risk
from clawock.safe_io import file_lock, safe_write_json


def _path(workspace):
    return workspace / 'memory' / '.tmp' / 'risk-card-notices.json'


def _read(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _state(row):
    return [row['state'], row['review_at'], row['decision_overdue'], row['reason'],
            row['acknowledged'], row['severity'], row['recurrence_count']]


def review(workspace, *, leg=None, now=None):
    """The brief shows the open queue; market cards show delivered-state changes."""
    view = risk.followups(workspace / 'memory' / 'risk_breaches.json',
                          leg=leg, now=now, limit=None)
    previous = _read(_path(workspace)) if leg else {}
    notices = [
        row for row in view['rows']
        if not leg or (previous.get(row['breach_id']) or {}).get('state') != _state(row)
    ]
    if leg:
        view['notices'] = notices[:3]
        view['notice_omitted'] = len(notices) - len(view['notices'])
        view['rows'] = view['rows'][:12]
        view['omitted'] = view['total'] - len(view['rows'])
    else:
        view['notices'] = notices
    return view


def record(workspace, view, body):
    """Advance only for rows in a successfully sent body, even on a fallback."""
    from clawock.harness.chat_card import risk_notice

    if not view or not view.get('notices'):
        return
    lines = set(body.splitlines())
    sent = [row for row in view['notices'] if risk_notice(row) in lines]
    if not sent:
        return
    path = _path(workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path):
            previous = _read(path)
            for row in sent:
                key = row['breach_id']
                if key and (previous.get(key) or {}).get('as_of', '') <= view['as_of']:
                    previous[key] = {'state': _state(row), 'as_of': view['as_of']}
            safe_write_json(str(path), previous)
    except OSError as exc:
        print(f'warn: risk card notice receipt write failed: {exc}', file=sys.stderr)
