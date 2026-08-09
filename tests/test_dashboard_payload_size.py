"""dashboard.json is a bounded cross-tab payload, not an archive.

Detail visitors download it, so a block nobody reads still taxes activation.
Two historical regressions had crept in: the leverage dial shipped twice in one
document, and 27KB of calibrator posterior state shipped with no consumer at all.
"""
import json
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "assets" / "data" / "dashboard.json"
OVERVIEW = ROOT / "assets" / "data" / "overview.json"
# Bytes, not characters — the unit build_dashboard's MAX_OUT_BYTES and
# system_check both use, and the only one a visitor actually downloads. This
# file used to measure `len(read_text())`, and because the payload is heavily
# CJK (3 bytes per character in UTF-8) it read 4.8% low: 186,308 "bytes" for a
# 195,234-byte file. That made the CI gate the loosest of the three and its
# headroom number a lie — 2026-07-28 it reported 13.7KB left when 4.7KB
# remained.
SIZE_CAP = 200_000            # == build_dashboard.MAX_OUT_BYTES
RENDERERS = ("dashboard.render.js", "dashboard.charts.js")


@pytest.fixture(scope="module")
def payload(freshly_built_dashboard):
    return json.loads(freshly_built_dashboard.read_text())


def _size(obj):
    return len(json.dumps(obj, ensure_ascii=False))


def _published_size():
    """Single source of truth for "how big is it" — see SIZE_CAP on the unit."""
    return len(DASHBOARD.read_bytes())


def test_payload_stays_under_the_published_cap(freshly_built_dashboard):
    size = _published_size()
    assert size < SIZE_CAP, f"{size:,} bytes; trim or move detail to a sidecar"


def test_overview_projection_keeps_canonical_money_health_and_generation_parity(
        freshly_built_dashboard):
    full = json.loads(freshly_built_dashboard.read_text())
    overview = json.loads(OVERVIEW.read_text())

    assert overview["schema_version"] == 1
    assert overview["projection"] == "overview"
    assert overview["generation_id"] == full["generated_at"]
    for field in ("generated_at", "fx", "totals", "build_status"):
        assert overview[field] == full[field]
    assert len(OVERVIEW.read_bytes()) < 80_000


def test_the_overview_projection_ships_every_execution_field_the_hero_renders(
        freshly_built_dashboard):
    """The Hero is the first-paint copy of a number the projection trims.

    `compile_overview_projection` deliberately keeps overview.json small, so the
    execution leg is a hand-listed field tuple. When `stranded` was added to the
    metric (#294) the detail card picked it up automatically and the Hero could
    not — it renders whatever `overview.json` happens to carry, which was
    `rate` and `known` only, i.e. the rate without the count of rows dropped
    from its denominator.

    Asserted against the projection function rather than the committed
    artifact, so it holds on the PR that changes the trim and not one publish
    later.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    import build_dashboard

    full = json.loads(freshly_built_dashboard.read_text())
    projected = build_dashboard.compile_overview_projection(full)
    shipped = ((projected.get("decision_metrics") or {})
               .get("execution_by_kind") or {}).get("active") or {}
    hero = (ROOT / "site" / "assets" / "js" / "dashboard.hero.js").read_text()
    rendered = set(re.findall(r"activeExec\.(\w+)", hero))

    assert rendered, "the Hero stopped reading the execution leg; update this test"
    missing = sorted(rendered - set(shipped))
    assert not missing, (
        f"the Hero renders {missing} but the overview projection does not ship "
        "them; it would silently show a rate with less context than the detail card")


def test_the_cap_is_measured_in_the_same_unit_the_builder_enforces(
        freshly_built_dashboard):
    """Three gates, one unit. The drift here was silent for a reason: on an
    ASCII payload the two units agree exactly, so nothing catches it until the
    content is non-ASCII — which this payload has always been."""
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    import build_dashboard
    from clawock.publish import artifacts as validate_sidecars

    assert SIZE_CAP == build_dashboard.MAX_OUT_BYTES
    assert SIZE_CAP == validate_sidecars.DASHBOARD_MAX_BYTES

    # The payload is CJK-heavy, so the two units are ~5% apart. Pinning the
    # gate's measurement to the byte count is what stops anyone quietly putting
    # `read_text()` back: on this content the assertion below can only hold for
    # the byte reading.
    characters = len(DASHBOARD.read_text())
    assert _published_size() > characters
    assert _published_size() == len(DASHBOARD.read_bytes())

    check = (ROOT / "ops" / "system_check.py").read_text()
    assert "out.stat().st_size" in check, "system_check must stay on bytes too"


def test_builder_does_not_spend_recovered_headroom_on_indentation():
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    import build_dashboard

    value = {"中文": {"rows": [1, 2]}, "status": "ok"}
    serialized = build_dashboard.serialize_dashboard_payload(value)
    assert serialized == '{"中文":{"rows":[1,2]},"status":"ok"}'
    assert len(serialized.encode("utf-8")) < len(
        json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    )


def test_no_sub_object_is_embedded_twice(payload):
    """The dial was embedded at top level and again inside risk_guardrail."""
    import hashlib

    seen = {}
    duplicates = []
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        for sub_key, sub_value in value.items():
            if _size(sub_value) < 2000:
                continue
            digest = hashlib.md5(
                json.dumps(sub_value, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            if digest in seen:
                duplicates.append(f"{seen[digest]} == {key}.{sub_key}")
            seen[digest] = f"{key}.{sub_key}"
        digest = hashlib.md5(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if digest in seen and _size(value) >= 2000:
            duplicates.append(f"{seen[digest]} == {key}")
        seen.setdefault(digest, key)
    assert duplicates == [], duplicates


def test_the_unread_history_and_calibrator_blocks_stay_out(payload):
    assert "regime_history" not in payload["lev_regime"]
    assert payload["lev_regime"]["regime_history_source"].endswith("lev_regime.json")
    assert "lev_regime" not in payload["risk_guardrail"]
    assert payload["risk_guardrail"]["lev_regime_tier"]      # the derived bit survives

    calibration = payload["decision_metrics"]["hierarchical_calibration"]
    assert "current_group_calibrators" not in calibration
    assert isinstance(calibration["current_group_calibrator_count"], int)
    # the headline fields the card renders are untouched
    for field in ("method", "hierarchy", "abstain_rule", "sizing_rule", "all_predictions"):
        assert field in calibration


def test_the_unread_workflow_stage_detail_stays_out(payload):
    """`recent[].stages` was 24KB of heartbeat detail with no reader.

    The build-status dot reads `counts` / `raw_error_but_product_usable`; its
    tooltip reads `job`, `slot`, `raw_execution.status`, `final_product.status`
    and nothing else. Assert both halves: the detail is gone, and every field
    the renderer names is still there.
    """
    wf = payload["workflow_outcomes"]
    # `recent` is deliberately NOT asserted non-empty. The ledger is pruned by
    # age, so a quiet stretch — a weekend, or any day without scheduled runs —
    # legitimately empties it, and requiring rows here made the suite go red on
    # live data rather than on a defect. (It is red on master right now for
    # exactly that reason.) A test assertion is the second carrier of live
    # numbers, and this was one. What the trim contract actually promises is the
    # shape below, which holds for zero rows as well as for many.
    assert isinstance(wf["recent"], list)
    assert all("stages" not in record for record in wf["recent"])
    # The pointer is written only when detail was actually dropped, so with an
    # empty ledger its absence is correct. The invariant is "if we trimmed, we
    # say where it went" — not "we always trimmed".
    assert wf.get("stages_source", "assets/data/workflow-outcomes.json").endswith(
        "workflow-outcomes.json")

    assert isinstance(wf["counts"], dict)
    assert "raw_error_but_product_usable" in wf
    for record in wf["recent"]:
        for field in ("job", "slot", "raw_execution", "final_product"):
            assert field in record, field
        assert record["raw_execution"]["status"]
        assert record["final_product"]["status"]


def test_dashboard_trim_keeps_readability_without_full_stage_detail():
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    import build_dashboard

    readability = {
        "status": "advisory", "bytes": 29_109,
        "target_bytes": 28_000, "extreme_bytes": 40_000,
        "over_by_bytes": 1_109,
    }
    summary = {
        "recent": [{
            "job": "盘前深度简报",
            "stages": {"llm": {"status": "success", "readability": readability}},
            "final_product": {"status": "success"},
        }],
    }

    trimmed = build_dashboard.trim_workflow_outcomes(summary)

    assert "stages" not in trimmed["recent"][0]
    assert trimmed["recent"][0]["readability"] == readability
    assert trimmed["stages_source"] == "assets/data/workflow-outcomes.json"


def test_dashboard_trim_prefers_current_llm_readability_on_same_slot_retry():
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    import build_dashboard

    current = {"status": "within_budget", "bytes": 27_000}
    stale = {"status": "advisory", "bytes": 29_000}
    summary = {"recent": [{
        "stages": {
            "llm": {"status": "success", "readability": current},
            "postflight": {"status": "success", "readability": stale},
        },
    }]}

    trimmed = build_dashboard.trim_workflow_outcomes(summary)

    assert trimmed["recent"][0]["readability"] == current


def test_dropped_blocks_are_still_reachable_elsewhere(payload):
    """Trimming the payload must not lose the data — only relocate it.

    `workflow-outcomes.json` moved to the data branch (#325), so "elsewhere" is
    no longer "in this checkout". The relocation claim is checked in whichever
    form the environment can support, and BOTH forms are real assertions:

    * the payload must say where the dropped stages went — that pointer is the
      entire relocation contract, and it is present in every environment;
    * where the file is actually on disk (the live host, or any checkout that
      fetched the generation) its content is checked too.

    Deliberately not `skipif`: a checkout without the file is the normal case
    now, and a test that skipped there would silently stop guarding anything.
    """
    standalone = json.loads((ROOT / "assets" / "data" / "lev_regime.json").read_text())
    assert standalone["regime_history"]["hk"]

    outcomes_path = ROOT / "assets" / "data" / "workflow-outcomes.json"
    summary = payload.get("workflow_outcomes") or {}
    if summary.get("stages_source"):
        assert summary["stages_source"] == "assets/data/workflow-outcomes.json", (
            "the payload points somewhere the stages are not")

    if outcomes_path.is_file():
        outcomes = json.loads(outcomes_path.read_text())
        assert any(record.get("stages") for record in outcomes["records"])


def test_what_the_charts_actually_read_is_still_present(payload):
    """Guards against over-trimming across the main payload/sidecar boundary."""
    js = "".join((ROOT / "site" / "assets" / "js" / name).read_text() for name in RENDERERS)
    assert 'safe(DATA, "decision_audit", "episode_backtest")' in js
    assert 'safe(DATA, "episode_backtest")' in js  # rollout fallback
    # The tracked artifact may still be from the pre-migration cron build on a
    # feature branch. The builder contract below forbids re-embedding it.
    if payload.get("episode_backtest"):
        assert payload["episode_backtest"]["horizons"]["t1"]
    assert payload["snapshots"]
    # the dial card reads these off the trimmed copy
    assert 'safe(DATA, "lev_regime")' in js
    for field in ("hk", "us", "as_of", "label", "ma_window"):
        assert field in payload["lev_regime"], field
    assert payload["lev_regime"]["us"]["names"]


def test_the_trim_survives_a_real_rebuild(freshly_built_dashboard):
    """The builder is run by the `freshly_built_dashboard` session fixture, not
    here: the money-reconciliation gate in `test_validate_sidecars` reads the
    same artifact and used to depend on this test having run first, which only
    held because `test_dashboard_...` sorts before `test_validate_...` (#298)."""
    rebuilt = json.loads(freshly_built_dashboard.read_text())
    assert "regime_history" not in rebuilt["lev_regime"]
    assert "current_group_calibrators" not in rebuilt["decision_metrics"]["hierarchical_calibration"]
    assert all("stages" not in r for r in rebuilt["workflow_outcomes"]["recent"])
    assert len(DASHBOARD.read_bytes()) < SIZE_CAP


def test_the_brief_still_gets_the_calibrators_the_dashboard_no_longer_ships():
    """Cross-PR interaction guard.

    The daily-brief skill requires an active call to match its group in
    `decision_metrics.hierarchical_calibration.current_group_calibrators` before
    any size multiplier applies (#62). The public payload stopped shipping that
    table (#102) because no chart reads it — which is only safe because the brief
    computes its metrics in-process rather than reading dashboard.json.

    Break either half and sizing silently loses its evidence base.
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    from clawock.decision import ledger as decision_v2

    metrics = decision_v2.compute_metrics(decision_v2.load_decisions())
    calibration = metrics.get("hierarchical_calibration") or {}
    assert isinstance(calibration.get("current_group_calibrators"), list)

    preflight = (ROOT / "instances" / "kcnyu" / "src" / "clawock_kcnyu" /
                 "harness" / "brief_preflight.py").read_text()
    computed = preflight.split("def compute_decision_metrics", 1)[1][:1500]
    assert "decision_v2.compute_metrics" in computed
    assert "dashboard.json" not in computed, "the brief must not source metrics from the trimmed payload"

    skill = (ROOT / "skills" / "daily-deep-brief" / "SKILL.md").read_text()
    assert "current_group_calibrators" in skill


def test_the_brief_only_ships_calibrator_rows_that_can_move_size():
    """The brief injects its context on every turn, so an all-abstain posterior
    table costs far more there than in the once-published payload (#131).

    Two things must hold together: the trim has to actually drop the dead rows,
    and it must be incapable of dropping a row that would have multiplied size.
    The second is the one worth a test — decision_v2 defines
    `edge_supported = not abstain and ci[0] > 0.5` and `evidence_sufficient =
    not abstain`, so edge-supported is a strict subset. If anyone ever inverts
    that relationship, sizing loses its evidence base silently.
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    sys.path.insert(0, str(ROOT / "instances" / "kcnyu" / "src"))
    from clawock.decision import ledger as decision_v2
    from clawock_kcnyu.harness import brief_preflight

    raw = decision_v2.compute_metrics(decision_v2.load_decisions())
    rows = raw["hierarchical_calibration"]["current_group_calibrators"]

    trimmed = brief_preflight.trim_abstaining_calibrators(raw)
    calibration = trimmed["hierarchical_calibration"]
    kept = calibration["current_group_calibrators"]

    # every dropped row is one both skills already treat as a missing row
    assert all(r.get("evidence_sufficient") for r in kept)
    assert all(not r.get("abstain") for r in kept)

    # the invariant that makes the filter safe, asserted on real ledger rows
    for row in rows:
        if row.get("edge_supported"):
            assert row.get("evidence_sufficient"), row
            assert row in kept, "a size-moving row was dropped"

    # nothing becomes invisible
    assert calibration["current_group_calibrator_count"] == len(rows)
    assert calibration["current_group_calibrators_omitted"] == len(rows) - len(kept)
    assert sum(calibration["omitted_abstain_reasons"].values()) == len(rows) - len(kept)
    assert calibration["omitted_rule"]

    # headline fields the skills read are untouched by the trim
    for field in ("method", "hierarchy", "abstain_rule", "sizing_rule",
                  "all_predictions", "after_warmup"):
        assert field in calibration, field


def test_the_published_provenance_names_a_workspace_relative_source(freshly_built_dashboard):
    """The payload states which previously published file it borrowed from (#262).

    Asserted on a real build because the value is only correct if `main()` passes
    it through `workspace_relative`: the live host and the brief-fallback Actions
    job build this file from different absolute roots, and `semantic_value()`
    does not strip the field, so an absolute path makes the two publishers
    alternate a commit that changes nothing a reader can see.
    """
    provenance = (json.loads(freshly_built_dashboard.read_text())
                  .get("build_status") or {}).get("previous_payload")

    assert provenance is not None, "a published payload must say what it reused"
    assert isinstance(provenance["preserved"], list)
    source = provenance["source"]
    assert source is None or not Path(source).is_absolute(), (
        f"provenance source {source!r} is machine-specific")
