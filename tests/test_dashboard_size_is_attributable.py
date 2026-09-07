"""A cap breach that cannot be attributed costs a session (#743, 2026-07-28).

`test_payload_stays_under_the_published_cap` builds from the REAL tree, and the
market data in that tree lands on master all day. So the gate can go red on a PR
that never touched the payload. Measured over 23 consecutive host runs the
payload ranged 182,073–200,465 bytes, moved up to 13,474 between one run and the
next, and crossed the cap once. `"203,000 bytes; trim something"` told the
reviewer that CI was red and nothing about whose fault it was.

The same measurement retired the old `near = 180_000` warning in system_check:
180,000 is BELOW the observed floor, so it fired on 23 of 23 runs — a warning
that is always on is not a warning.
"""
import json

from clawock.publish import dashboard


PAYLOAD = {
    "decision_traces": ["x" * 400],
    "snapshots": ["y" * 200],
    "fx": {"usdhkd": 7.84},
}


def test_blocks_are_reported_biggest_first():
    blocks = dashboard.payload_blocks_by_size(PAYLOAD)

    assert [key for key, _ in blocks] == ["decision_traces", "snapshots", "fx"]
    assert all(a[1] >= b[1] for a, b in zip(blocks, blocks[1:]))


def test_sizes_are_bytes_not_characters():
    """The payload is heavily CJK; characters read ~5% low and that gap is the
    whole headroom. Same unit as the cap, or the number is a lie (#743)."""
    blocks = dashboard.payload_blocks_by_size({"cn": "港股"})

    assert blocks[0][1] == len(json.dumps("港股", ensure_ascii=False).encode("utf-8"))


def test_every_block_is_accounted_for():
    """A breakdown that quietly drops blocks would send the reader after the
    wrong one."""
    blocks = dashboard.payload_blocks_by_size(PAYLOAD)

    assert {key for key, _ in blocks} == set(PAYLOAD)


def test_the_description_names_the_biggest_blocks_and_the_headroom():
    text = dashboard.describe_payload_size(PAYLOAD, 190_491, 200_000, top=2)

    assert "190,491" in text
    assert "9,509" in text                 # headroom, stated not implied
    assert "decision_traces" in text
    assert "snapshots" in text
    assert "fx" not in text                # top=2 honoured


def test_an_empty_payload_does_not_crash_the_report():
    assert dashboard.describe_payload_size({}, 0, 200_000)


def test_the_ci_gate_uses_the_shared_describer():
    """Two reports of the same payload must not describe it differently."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "tests" / "test_dashboard_payload_size.py").read_text()

    assert "describe_payload_size" in source
    assert 'f"{size:,} bytes; trim or move detail to a sidecar"' not in source


def test_system_check_reports_composition_and_a_threshold_that_discriminates():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "ops" / "system_check.py").read_text()

    # The retired premise and the always-on threshold, both gone.
    assert "The payload only grows" not in source
    assert "cap, near = 200_000, 180_000" not in source
    # …replaced by one derived from the observed run-to-run swing.
    assert "swing = 14_000" in source
    assert "describe_payload_size" in source
