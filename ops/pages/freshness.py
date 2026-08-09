#!/usr/bin/env python3
"""Trace one dashboard generation across every layer between producer and browser.

Each layer already had a way to look healthy on its own. The publisher logs a
successful build, the data branch shows a recent force-update, the Pages workflow
reports success, and the site returns 200 — and the browser can still be reading
a generation from yesterday, because "green" at one layer says nothing about
whether the next one consumed it. Twice now the visible symptom was only that the
dashboard "did not refresh".

So this asks one question end to end: **which generation is each layer serving,
and is the distance between them explainable?**

    producer            the workspace that built it   assets/data/dashboard.json
    data plane          orphan `data-plane` branch    the publisher force-updates
    Pages deployment    the last successful deploy    what GitHub says it served
    live                the URL a browser fetches     kcnyu.github.io/...

A lag is not automatically a fault: the host publisher runs every 20 minutes, and
a Pages deployment reports success roughly 14 minutes before the new content is
actually served. Both are bounded and expected, so they are reported as
`behind (within bound)` rather than as failures. Anything beyond that is a real
stall and exits non-zero, because the whole point is that a frozen dashboard used
to be indistinguishable from a quiet one.

Read-only: no fetch, no build, no publish.

Run: python3 ops/pages/freshness.py [--json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[2]
PAYLOAD = "assets/data/dashboard.json"
DATA_PLANE_REF = "origin/data-plane"
LIVE_URL = f"https://kcnyu.github.io/clawock/{PAYLOAD}"

# How far a layer may trail the newest generation before it is a stall rather
# than a queue. Measured as reference.generated_at - layer.generated_at, NOT as
# now - layer.generated_at: the second conflates "this generation is old" with
# "the pipeline is stuck", and on a quiet night every layer would look stale
# while being perfectly in sync.
#
# The host publisher runs at :00/:20/:40, so the data plane trails by up to one
# tick plus the build.
DATA_PLANE_BOUND = timedelta(minutes=25)
# Then the dispatch, the Pages build, and a CDN propagation that lands roughly
# 14 minutes after the deployment already reports success. One publisher tick on
# top, because the deploy is triggered by the tick that produced the generation.
LIVE_BOUND = timedelta(minutes=45)
# Consistency is not freshness: if the builder stops, every layer keeps agreeing
# on the same generation and this trace stays green while the dashboard ages.
#
# But liveness cannot be read off `generated_at`. The publisher deliberately does
# not advance the generation when a rebuild is semantically identical — that is
# the #312 guarantee that a file whose only change is the build clock never gets
# published — so on a quiet night the timestamp standing still is the correct
# state, not a stall. My first version of this check called that a stall and
# cried wolf on the first run.
#
# The honest evidence that the builder ran is that it wrote the file. Available
# only on the producing host; elsewhere the layer is absent and so is the check.
PRODUCER_BOUND = timedelta(minutes=30)


@dataclass
class Layer:
    name: str
    # "generation" layers serve the payload and are compared by generation id.
    # The deployment layer serves nothing — it records when GitHub last shipped —
    # so comparing its commit sha against a generation id would mark it different
    # every single time and then age it out. It is judged on timing instead.
    kind: str = "generation"
    generation: str | None = None
    generated_at: datetime | None = None
    detail: str = ""
    # When the builder last WROTE this layer, as opposed to which generation it
    # holds. The two answer different questions and only the host can answer this.
    wrote_at: datetime | None = None
    build_status: dict | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.generation is not None and not self.problems


def _parse(payload: str, name: str) -> Layer:
    layer = Layer(name)
    try:
        data = json.loads(payload)
    except Exception as exc:
        layer.problems.append(f"unreadable payload: {exc}")
        return layer
    stamp = data.get("generated_at")
    layer.generation = data.get("generation_id") or stamp
    # The payload carries its own market-session verdict on its inputs. Reading
    # it here is what makes this a freshness trace rather than a sameness trace,
    # and it avoids a second copy of the trading-hours table drifting from the
    # one the builder already uses.
    status = data.get("build_status")
    if isinstance(status, dict):
        layer.build_status = {
            "healthy": status.get("healthy"),
            "stale_files": status.get("stale_files") or [],
            "stale_markets": status.get("stale_markets") or [],
        }
    try:
        layer.generated_at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except Exception:
        layer.problems.append(f"unparseable generated_at: {stamp!r}")
    return layer


def read_producer(workspace: Path) -> Layer:
    path = workspace / PAYLOAD
    if not path.is_file():
        # Expected off the live host: the payloads are not tracked any more, so a
        # fresh checkout has no producer layer to report. Absence is not a fault.
        return Layer("producer", detail=f"no local {PAYLOAD} (not the producing host)")
    layer = _parse(path.read_text(encoding="utf-8"), "producer")
    layer.detail = str(path)
    layer.wrote_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return layer


def read_data_plane(checkout: Path) -> Layer:
    fetch = subprocess.run(["git", "fetch", "--quiet", "origin", "data-plane"],
                           cwd=checkout, capture_output=True, text=True)
    show = subprocess.run(["git", "show", f"{DATA_PLANE_REF}:{PAYLOAD}"],
                          cwd=checkout, capture_output=True, text=True)
    if show.returncode != 0:
        layer = Layer("data plane")
        layer.problems.append(
            (fetch.stderr or show.stderr or "branch not readable").strip()[:200])
        return layer
    layer = _parse(show.stdout, "data plane")
    layer.detail = DATA_PLANE_REF
    return layer


def read_deployment() -> Layer:
    """What GitHub says it last deployed, via `gh`. Optional: no token, no layer."""
    layer = Layer("pages deployment", kind="deployment")
    done = subprocess.run(
        ["gh", "api", "repos/KCNyu/clawock/deployments?environment=github-pages&per_page=1",
         "--jq", ".[0] | {created_at, sha}"],
        capture_output=True, text=True)
    if done.returncode != 0:
        layer.detail = "gh unavailable or unauthenticated — layer skipped"
        return layer
    try:
        info = json.loads(done.stdout or "{}")
        layer.generated_at = datetime.fromisoformat(
            info["created_at"].replace("Z", "+00:00"))
        layer.generation = info.get("sha", "")[:12]
        layer.detail = f"deployment {layer.generation}"
    except Exception as exc:
        layer.problems.append(f"unreadable deployment: {exc}")
    return layer


def read_live(url: str = LIVE_URL) -> Layer:
    try:
        import requests
        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except Exception as exc:
        layer = Layer("live")
        layer.problems.append(f"{type(exc).__name__}: {exc}")
        return layer
    layer = _parse(response.text, "live")
    layer.detail = url
    return layer


def assess(layers: list[Layer], now: datetime | None = None) -> dict:
    """Same generation everywhere, or a lag each side can be held to."""
    now = now or datetime.now(timezone.utc)
    reference = next((layer for layer in layers
                      if layer.name == "producer" and layer.ok), None)
    reference = reference or next((layer for layer in layers if layer.ok), None)

    findings: list[str] = []
    # Has the builder run at all recently? Only the producing host can say.
    producer = next((layer for layer in layers if layer.name == "producer"), None)
    if producer and producer.wrote_at:
        silent = now - producer.wrote_at
        if silent > PRODUCER_BOUND:
            findings.append(
                f"the builder has not written for {int(silent.total_seconds() // 60)}m "
                f"— it runs every 20m, so the layers agreeing below means production "
                f"stopped, not that the pipeline is healthy")
    live = next((layer for layer in layers if layer.name == "live" and layer.ok), None)
    rows = []
    for layer in layers:
        status = "ok"
        note = layer.detail
        if layer.problems:
            status = "unreachable"
            note = "; ".join(layer.problems)
            findings.append(f"{layer.name}: {note}")
        elif layer.generation is None:
            status = "skipped"
        elif layer.kind == "deployment":
            # Consistent means "the generation the browser is being served has
            # already been deployed". A deployment older than what is live would
            # mean the site is serving something GitHub never shipped.
            if live and live.generated_at and layer.generated_at:
                if layer.generated_at >= live.generated_at:
                    note = f"shipped {layer.generation} after the live generation"
                else:
                    behind = live.generated_at - layer.generated_at
                    if behind <= LIVE_BOUND:
                        status = "deploy pending"
                        note = (f"newest generation is {int(behind.total_seconds() // 60)}m "
                                f"newer than the last deploy, bound "
                                f"{int(LIVE_BOUND.total_seconds() // 60)}m")
                    else:
                        status = "STALE"
                        note = (f"last deploy is {int(behind.total_seconds() // 60)}m "
                                f"older than the live generation")
                        findings.append(f"{layer.name} is stale: {note}")
            else:
                status = "skipped"
                note = "no live layer to compare against"
        elif reference and layer.generation != reference.generation:
            bound = {"data plane": DATA_PLANE_BOUND}.get(layer.name, LIVE_BOUND)
            behind = (
                reference.generated_at - layer.generated_at
                if layer.generated_at and reference.generated_at else None)
            if behind is not None and behind <= bound:
                status = "behind (within bound)"
                note = (f"{int(behind.total_seconds() // 60)}m behind the newest "
                        f"generation, bound {int(bound.total_seconds() // 60)}m")
            else:
                status = "STALE"
                age = (f"{int(behind.total_seconds() // 60)}m behind"
                       if behind else "distance unknown")
                note = f"{age} the newest generation, past the {int(bound.total_seconds() // 60)}m bound"
                findings.append(f"{layer.name} is stale: {note}")
        rows.append({
            "layer": layer.name,
            "generation": layer.generation,
            "generated_at": layer.generated_at.isoformat() if layer.generated_at else None,
            "status": status,
            "note": note,
        })

    # What the browser is served says about its own inputs, for this session.
    served = next((layer for layer in layers if layer.name == "live" and layer.build_status),
                  None) or next((layer for layer in layers if layer.build_status), None)
    inputs = served.build_status if served else None
    if inputs and inputs.get("healthy") is False:
        stale = ", ".join(inputs["stale_files"] + inputs["stale_markets"]) or "unnamed inputs"
        findings.append(f"the served payload reports stale inputs for this session: {stale}")

    return {
        "checked_at": now.isoformat(),
        "served_inputs": inputs,
        "reference": reference.generation if reference else None,
        "layers": rows,
        "consistent": all(row["status"] in ("ok", "skipped") for row in rows),
        "findings": findings,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 ops/pages/freshness.py",
        description="Trace one dashboard generation from producer to browser.")
    parser.add_argument("--workspace", type=Path, default=Path("/root/.openclaw/workspace"),
                        help="the producing workspace (default: the live host's)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    layers = [read_producer(args.workspace), read_data_plane(CHECKOUT),
              read_deployment(), read_live()]
    report = assess(layers)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"reference generation: {report['reference']}\n")
        print(f"{'layer':<18}{'status':<22}{'generated_at':<34}note")
        print("─" * 110)
        for row in report["layers"]:
            print(f"{row['layer']:<18}{row['status']:<22}"
                  f"{str(row['generated_at'] or '—'):<34}{row['note']}")
        print()
        inputs = report.get("served_inputs")
        if inputs is not None:
            verdict = "fresh for this session" if inputs.get("healthy") else "STALE INPUTS"
            print(f"served payload inputs: {verdict}"
                  + (f" — {', '.join(inputs['stale_files'] + inputs['stale_markets'])}"
                     if not inputs.get("healthy") else "") + "\n")
        if report["consistent"] and not report["findings"]:
            print("✅ every layer is serving the same generation")
        elif report["findings"]:
            for finding in report["findings"]:
                print(f"🔴 {finding}")
        else:
            print("🟡 layers differ, all within their documented bounds")
    return 0 if not report["findings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
