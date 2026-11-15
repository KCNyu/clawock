"""Browser-bound JSON never carries bare NaN/Infinity.

Python's `json.dumps` writes both tokens by default; `JSON.parse` rejects
them. #3477 fixed the decision-packet writer; these are its siblings in the
brief context and the dashboard payload (#3511).
"""
import json

from clawock.context import brief
from clawock.publish import dashboard


def test_brief_compact_replaces_non_finite_with_null():
    text = brief._compact({'x': float('inf'), 'y': [float('nan'), 1]})
    assert 'Infinity' not in text and 'NaN' not in text
    assert json.loads(text) == {'x': None, 'y': [None, 1]}


def test_dashboard_payload_serializes_non_finite_as_null():
    text = dashboard.serialize_dashboard_payload(
        {'book': {'total_current_value': float('nan')}})
    assert 'NaN' not in text
    assert json.loads(text) == {'book': {'total_current_value': None}}
