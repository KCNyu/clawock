---
layout: default
title: clawock · research lifecycle cadence
---

# Research lifecycle cadence

Which research question gets asked how often, and why that cadence and not a
faster one. The rule throughout: **detection is cheap and runs daily; production
is expensive and runs on an event.** Nothing here adds a cron job, and nothing
heavy enters an intraday path.

| Question | Cadence | Where it runs | Cost |
|---|---|---|---|
| Are the thesis, earnings and entry-gate artifacts still valid? | every push, every PR | `ops/system_check.py` (pre-push) · `validate` job (`research_surface.py --check`) | local file reads |
| What is each holding's thesis state and next review trigger? | daily | `brief_preflight.py` → `context.thesis_registry` | local file reads |
| Is an earnings review due, a promise overdue, a position ungated? | daily | `brief_preflight.py` → `context.research_surface` | local file reads |
| Should this thesis change? | on new evidence | `thesis_registry.py drift` after an earnings artifact or a red-line event | one agent turn |
| Review a reported quarter | on the report | `earnings-review` skill, manual/event-driven | one deep turn + filings |
| Screen a new name | before a research run | `entry-gate` skill, manual | one cheap turn |
| Verify a published number | at release | `research_provenance.py` inside `earnings_review.release()` | local, deterministic |

## Why the daily items are daily

They read local JSON only — no network, no LLM, no market data. Running them in
the 08:00 brief preflight costs nothing measurable and puts the answer in front of
the one process that already reports every morning. That is the whole reason they
are daily: a work queue nobody sees is the same as no queue.

## Why the expensive items are not daily

A full earnings review reads primary filings and produces a manifest-backed
artifact. Running that daily would either burn a deep turn per holding per day or,
worse, teach the model to re-narrate yesterday's numbers. It runs when an issuer
actually reports. The same logic keeps the entry gate on demand: a name that is not
being considered needs no gate, and a name being considered needs one before the
expensive research, not on a schedule.

Thesis drift is deliberately *not* daily either. A daily drift pass with no new
evidence produces prose churn — exactly the "intact / weakening / broken" wording
drift the registry exists to prevent. Drift runs when evidence arrives.

## Two detectors for "review due", on purpose

`reviews_due` reads `assets/data/catalysts.json`, which the brief preflight
refreshes each morning across a rotating window. It is precise but bounded: once a
reported date rotates out of that window, this detector goes quiet. The summary
carries `detection_window_days` so the bound is visible rather than implied.

`stale_ledgers` covers the long run and needs no feed at all. It compares the
newest artifact's period end against the issuer's own cadence (quarterly,
semiannual, annual) and flags a ledger left more than 1.6 periods behind. The
factor allows a normal reporting lag while still catching a period that was
skipped entirely.

Together: the catalyst detector catches a miss the morning after it happens, and
the cadence detector keeps a forgotten ledger visible indefinitely.

## Integrity versus work queue

`research_surface.check()` separates the two on purpose:

- **integrity failures fail closed** — an invalid artifact, or an entry gate whose
  stated verdict no longer matches the recomputed one, reds `system_check.py` and
  the `validate` job;
- **work items warn** — a due review, an overdue promise or an ungated position is
  the human's queue, not repository corruption, and must never block a runtime data
  publish. The live workspace commits generated data all day; a research to-do has
  no business stopping it.
