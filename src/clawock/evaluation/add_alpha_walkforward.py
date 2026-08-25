"""Point-in-time replay of low-frequency price-relative × information adds.

The command name is retained for CLI compatibility.  The report is explicit
about evidence grade: parameters are pre-registered rather than fitted, and
the current curated factor universe creates survivorship-limited diagnostics.
Prospective activation still requires newly collected sessions.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from clawock import history_store
from clawock.decision import add_alpha, early_trend, signals
from clawock.evidence import news_evidence_graph, run_card
from clawock.market_data import factors, peer_residuals
from clawock.workspace import workspace_root
from clawock.safe_io import to_number as _number


WS = workspace_root(Path.cwd())
FACTOR_CONFIG = WS / "config" / "factor-universe.json"
ALPHA_POLICY = WS / "config" / "add-alpha-policy.json"
NEWS_POLICY = WS / "config" / "news-evidence-policy.json"
FACTOR_HISTORY = WS / "assets" / "data" / "cross_sectional_factor_history.jsonl"
PEER_HISTORY = WS / "assets" / "data" / "peer_residual_history.jsonl"
NEWS_HISTORY = WS / "assets" / "data" / "news_evidence_history.jsonl"
PEER_MAP = WS / "memory" / "peer-map.json"
HORIZONS = (1, 5, 20)
VARIANTS = ("setup_only", "price_relative", "information", "interaction")


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _jsonl(path):
    # 归档 + 热窗（#951）：point-in-time 回放是从第一行开始的，读窗口一短，
    # episode 统计与评估区间就跟着变 —— 这正是当初不能「顺手加 cap」的原因。
    return history_store.load_series(path)




def _market(ticker, config_by_ticker):
    return str((config_by_ticker.get(ticker) or {}).get("region") or "").lower()


def _midrank(values, value):
    if value is None or not values:
        return None
    ordered = sorted(values)
    positions = [index for index, item in enumerate(ordered) if item == value]
    return statistics.fmean(positions) / max(1, len(ordered) - 1)


def _technical_at(bars, signal_date):
    known = [row for row in bars if row.get("date") <= signal_date]
    if not known or known[-1].get("date") != signal_date:
        return None
    row = signals.compute_signals(known)
    if not row:
        return None
    return {
        "close": row.get("close"),
        "prior_5d_high": row.get("prior_5d_high"),
        "prior_5d_low": row.get("prior_5d_low"),
        "prior_20d_high": row.get("prior_20d_high"),
        "chandelier_stop": row.get("chandelier_stop"),
        "ma20": row.get("ma20"),
        "zscore20": row.get("zscore20"),
        "usable": True,
        "as_of": signal_date,
    }


def _confirmation_fill(bars, signal_date, window=5):
    technical = _technical_at(bars, signal_date)
    levels = add_alpha.confirmation_levels(technical or {})
    if not levels:
        return None
    after = [row for row in bars if row.get("date") > signal_date][:window]
    for row in after:
        outcome = add_alpha.confirmation_bar_outcome(
            row,
            entry_price=levels["entry_price"],
            invalidation_price=levels["invalidation_price"],
        )
        if outcome["state"] in {"invalidated", "not_evaluable"}:
            return None
        if outcome["state"] == "filled":
            return {
                "session": row["date"],
                "price": outcome["price"],
                "fill_reason": outcome["reason"],
                **levels,
            }
    return None


def _forward_return(bars, entry_session, entry_price, horizon):
    index = next(
        (i for i, row in enumerate(bars) if row.get("date") == entry_session), None
    )
    if index is None or index + horizon >= len(bars) or not entry_price:
        return None
    return bars[index + horizon]["close"] / entry_price - 1


def _close_forward_return(bars, signal_date, horizon):
    """Signal after session close; first measurable horizon is a later close."""
    index = next(
        (i for i, row in enumerate(bars) if row.get("date") == signal_date), None
    )
    if index is None or index + horizon >= len(bars):
        return None
    entry = _number(bars[index].get("close"))
    future = _number(bars[index + horizon].get("close"))
    return future / entry - 1 if entry and future is not None else None


def _events_at(snapshot, ticker):
    return [
        {
            "event_id": event.get("event_id"),
            "source_type": event.get("source_type"),
            "direction": event.get("impact_direction"),
        }
        for event in snapshot.get("events") or []
        if str(event.get("ticker") or "") == ticker
    ]


def _cluster_ci(rows, field, samples=1000):
    by_date = defaultdict(list)
    for row in rows:
        value = _number(row.get(field))
        if value is not None:
            by_date[row["date"]].append(value)
    dates = sorted(by_date)
    if len(dates) < 3:
        return None
    rnd = random.Random(20260813)
    draws = []
    for _ in range(samples):
        chosen = [rnd.choice(dates) for _ in dates]
        values = [value for day in chosen for value in by_date[day]]
        draws.append(statistics.fmean(values))
    draws.sort()
    return [
        round(draws[int(0.025 * (len(draws) - 1))], 6),
        round(draws[int(0.975 * (len(draws) - 1))], 6),
    ]


def _summary(rows):
    values = [row["return"] for row in rows]
    excess = [row["excess_vs_setup"] for row in rows if row.get("excess_vs_setup") is not None]
    return {
        "n": len(rows),
        "n_dates": len({row["date"] for row in rows}),
        "n_tickers": len({row["ticker"] for row in rows}),
        "mean_return": round(statistics.fmean(values), 6) if values else None,
        "hit_rate": round(sum(value > 0 for value in values) / len(values), 4)
        if values else None,
        "mean_excess_vs_same_date_setup": (
            round(statistics.fmean(excess), 6) if excess else None
        ),
        "excess_date_cluster_ci95": _cluster_ci(rows, "excess_vs_setup"),
        "status": (
            "diagnostic"
            if len({row["date"] for row in rows}) >= 8 and len(rows) >= 20
            else "collecting"
        ),
    }


def _snapshot_cutoff(snapshot):
    raw = snapshot.get("observed_at") or f'{str(snapshot.get("as_of") or "")[:10]}T23:59:59+00:00'
    try:
        cutoff = datetime.fromisoformat(str(raw))
        return cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _attention_snapshot(snapshot, overlay_policy):
    cutoff = _snapshot_cutoff(snapshot)
    scores = defaultdict(float)
    signed = defaultdict(float)
    source_types = defaultdict(set)
    positive_components = defaultdict(list)
    attention_components = defaultdict(list)
    if cutoff is None:
        return {}
    for event in snapshot.get("events") or []:
        ticker = str(event.get("ticker") or "")
        if not ticker or ticker == "MARKET":
            continue
        payload = {
            "event_id": event.get("event_id"),
            "ticker": ticker,
            "impact_direction": event.get("impact_direction"),
            "publication_time": {"iso": event.get("published_at")},
            "novelty_score": event.get("novelty_score"),
            "source_reliability": event.get("source_reliability"),
            "source_type": event.get("source_type"),
            "corroborating_source_count": 1,
            "confirmation": {},
        }
        attention = news_evidence_graph._event_attention_component(
            payload, cutoff, overlay_policy
        )
        if attention:
            # The comparable value, not attention_value: this score is the
            # numerator of an acceleration ratio whose baseline is rebuilt
            # from the same corroboration-less snapshots. Identical today
            # because the payload above pins one source, but reading the
            # weighted field would silently reintroduce the asymmetry the
            # moment replay learns real corroboration counts.
            scores[ticker] += attention["baseline_comparable_value"]
            source_types[ticker].add(attention["source_type"])
            attention_components[ticker].append(attention)
        signed_value = _number(event.get("information_signed_score"))
        if signed_value is not None:
            signed[ticker] += signed_value
            if signed_value > 0:
                positive_components[ticker].append({
                    "event_id": event.get("event_id"),
                    "direction": 1,
                    "novelty": _number(event.get("novelty_score")) or 0,
                    "reliability": _number(event.get("source_reliability")) or 0,
                    "price_nonreaction": 1.0,
                })
    return {
        "attention": dict(scores),
        "signed": dict(signed),
        "source_types": {ticker: len(values) for ticker, values in source_types.items()},
        "positive_components": dict(positive_components),
        "attention_components": dict(attention_components),
    }


def _news_by_date(history, overlay_policy, config_by_ticker, prior=0.1):
    """Rebuild every attention feature using earlier snapshots only."""
    out = {}
    prior_scores = defaultdict(list)
    for snapshot in history:
        day = str(snapshot.get("as_of") or "")[:10]
        current = _attention_snapshot(snapshot, overlay_policy)
        if not day:
            continue
        tickers = set(config_by_ticker) | set(current.get("attention") or {})
        ranks = {}
        for market in ("hk", "us"):
            names = [ticker for ticker in tickers if _market(ticker, config_by_ticker) == market]
            values = [(current.get("attention") or {}).get(ticker, 0.0) for ticker in names]
            for ticker in names:
                ranks[ticker] = _midrank(
                    values, (current.get("attention") or {}).get(ticker, 0.0)
                )
        rows = {}
        for ticker in tickers:
            score = (current.get("attention") or {}).get(ticker, 0.0)
            baseline = statistics.fmean(prior_scores[ticker]) if prior_scores[ticker] else 0.0
            rows[ticker] = {
                "signed_score": (current.get("signed") or {}).get(ticker, 0.0),
                "event_components": (current.get("positive_components") or {}).get(ticker, []),
                "attention_score": score,
                "attention_rank": ranks.get(ticker),
                "attention_acceleration": (score + prior) / (baseline + prior),
                "attention_source_type_count": (current.get("source_types") or {}).get(ticker, 0),
                "attention_event_count": len(
                    (current.get("attention_components") or {}).get(ticker, [])
                ),
                "attention_components": (current.get("attention_components") or {}).get(ticker, []),
                "usable_for_decisions": False,
            }
        out[day] = {
            "rows": rows,
            "backfill": bool(snapshot.get("information_overlay_backfill")),
        }
        for ticker in tickers:
            prior_scores[ticker].append((current.get("attention") or {}).get(ticker, 0.0))
    return out


def _factor_rows(snapshot, config_by_ticker):
    rows = snapshot.get("rows") or {}
    by_market = defaultdict(list)
    for ticker, row in rows.items():
        score = _number(row.get("composite_score"))
        if score is not None:
            by_market[_market(ticker, config_by_ticker)].append(score)
    sector_sizes = defaultdict(int)
    for spec in config_by_ticker.values():
        sector_sizes[(spec["region"], spec["sector"])] += 1
    out = {}
    for ticker, row in rows.items():
        spec = config_by_ticker.get(ticker) or {}
        score = _number(row.get("composite_score"))
        out[ticker] = {
            "market_percentile": (
                _number(row.get("market_percentile"))
                if row.get("market_percentile") is not None
                else _midrank(by_market[_market(ticker, config_by_ticker)], score)
            ),
            "coverage_pct": _number(row.get("factor_coverage_pct")) or 0,
            "sector_universe_size": int(
                row.get("sector_universe_size")
                or sector_sizes[(spec.get("region"), spec.get("sector"))]
            ),
            "usable_for_decisions": False,
        }
    return out


def evaluate(config, policy, news_policy, fetched, factor_history, peer_history, news_history):
    specs = {row["ticker"]: row for row in config["symbols"]}
    # Legacy snapshots already froze every raw fact at their daily cutoff.
    # Reconstruct the newly registered deterministic components in memory; do
    # not require a generated-history rewrite for a reproducible evaluation.
    news_history = news_evidence_graph._backfill_information_components(
        news_policy,
        copy.deepcopy(news_history),
        datetime(2026, 8, 13, tzinfo=timezone.utc),
    )
    # #666: explicit None check, never `X or DEFAULT` — a config value of 0
    # (`attention_score_prior: 0`) is legal and must not be swallowed into
    # the 0.1 default.
    raw_attention_prior = policy.get("attention_score_prior")
    news = _news_by_date(
        news_history,
        news_policy["information_overlay"],
        specs,
        prior=float(raw_attention_prior) if raw_attention_prior is not None else 0.1,
    )
    news_snapshots = {
        str(snapshot.get("as_of") or "")[:10]: snapshot
        for snapshot in news_history
    }
    taxonomy, _ = peer_residuals.build_taxonomy(config, _json(PEER_MAP))
    canonical_taxonomy = {
        row["signal_ticker"]: row
        for _, row in peer_residuals._canonical_taxonomy_items(taxonomy)
    }
    peer_weight_cap = float(
        _json(peer_residuals.RULE_CONFIG)["basket_weight_cap"]
    )
    peers = {
        str(snapshot.get("as_of") or "")[:10]: snapshot.get("rows") or {}
        for snapshot in peer_history
    }
    observations = {
        market: {variant: {horizon: [] for horizon in HORIZONS} for variant in VARIANTS}
        for market in ("us", "hk")
    }
    coverage = {"factor_dates": 0, "information_dates": len(news), "overlap_dates": 0}
    authority_counts = {"none": 0, "exploration": 0, "validated": 0}
    early_observations = {
        market: {
            state: {horizon: [] for horizon in (1, 5)}
            for state in ("observed", "information_confirmed", "exploration_ready")
        }
        for market in ("us", "hk")
    }
    early_coverage = {
        "eligible_signal_dates": 0,
        "peer_metrics_evaluated": 0,
        "observed_candidates": 0,
        "information_confirmed": 0,
        "exploration_ready": 0,
        "missing_taxonomy": 0,
    }
    seen_early = set()
    for snapshot in factor_history:
        snapshot_date = str(snapshot.get("as_of") or "")[:10]
        if not snapshot_date:
            continue
        coverage["factor_dates"] += 1
        if snapshot_date in news:
            coverage["overlap_dates"] += 1
        ranked = _factor_rows(snapshot, specs)
        for ticker, factor_row in ranked.items():
            spec = specs.get(ticker)
            bars = (fetched.get(ticker) or {}).get("bars") or []
            signal_date = str(
                ((snapshot.get("rows") or {}).get(ticker) or {}).get("feature_as_of")
                or snapshot_date
            )[:10]
            if not spec or not bars:
                continue
            fill = _confirmation_fill(
                bars, signal_date, int(policy["confirmation_window_sessions"])
            )
            if not fill:
                continue
            peer_row = (peers.get(signal_date) or peers.get(snapshot_date) or {}).get(ticker) or {}
            peer_view = {
                "triggered_rules": peer_row.get("triggered_rules") or [],
                "available_peer_count": int(peer_row.get("available_peer_count") or 0),
                "usable_for_decisions": False,
            }
            info = ((news.get(signal_date) or news.get(snapshot_date) or {}).get("rows") or {}).get(ticker) or {}
            authority = add_alpha.classify_authority(
                factor_row,
                peer_view,
                info,
                leveraged=False,
                policy=policy,
                market=spec["region"],
            )
            authority_counts[authority["tier"]] += 1
            factor_ok = add_alpha._factor_support(
                factor_row, policy["markets"][spec["region"].upper()]
            )[0]
            peer_ok = add_alpha._peer_support(
                peer_view, policy["markets"][spec["region"].upper()]
            )[0]
            information_ok = add_alpha._information_support(
                info, policy, policy["markets"][spec["region"].upper()]
            )[0]
            selected = {
                "setup_only": True,
                "price_relative": factor_ok or peer_ok,
                "information": information_ok,
                "interaction": authority["tier"] in {"exploration", "validated"},
            }
            for horizon in HORIZONS:
                value = _forward_return(
                    bars, fill["session"], fill["price"], horizon
                )
                if value is None:
                    continue
                for variant, include in selected.items():
                    if include:
                        observations[spec["region"]][variant][horizon].append({
                            "date": signal_date,
                            "ticker": ticker,
                            "return": value,
                            "fill_reason": fill["fill_reason"],
                        })
        # Early lane is evaluated independently of the mature setup/fill lane.
        # One row per economic exposure (never both SPCX and SPCH), using only
        # bars and information snapshots available at the signal-date close.
        for ticker, taxonomy_row in canonical_taxonomy.items():
            spec = specs.get(ticker)
            bars = (fetched.get(ticker) or {}).get("bars") or []
            if not spec or not bars:
                continue
            signal_date = str(
                ((snapshot.get("rows") or {}).get(ticker) or {}).get("feature_as_of")
                or snapshot_date
            )[:10]
            observation_key = (ticker, signal_date)
            if observation_key in seen_early:
                continue
            seen_early.add(observation_key)
            technical = _technical_at(bars, signal_date)
            if not technical:
                continue
            early_coverage["eligible_signal_dates"] += 1
            peer_metrics = peer_residuals.metrics_at(
                taxonomy_row, fetched, signal_date,
                peer_weight_cap,
            )
            if not peer_metrics:
                continue
            early_coverage["peer_metrics_evaluated"] += 1
            peer_view = {
                "residual_5d": peer_metrics.get("residual_blend_5d"),
                "dispersion_5d": peer_metrics.get("peer_dispersion_5d"),
                "available_peer_count": peer_metrics.get("available_peer_count"),
            }
            info = ((news.get(signal_date) or {}).get("rows") or {}).get(ticker) or {}
            candidate = early_trend.classify(
                technical, peer_view, info,
                _events_at(news_snapshots.get(signal_date) or {}, ticker),
                leveraged=False, policy=policy, market=spec["region"],
            )
            if not candidate["observed"]:
                continue
            early_coverage["observed_candidates"] += 1
            info_confirmed = "point_in_time_information" in candidate["evidence_families"]
            early_coverage["information_confirmed"] += int(info_confirmed)
            early_coverage["exploration_ready"] += int(candidate["exploration_ready"])
            states = ["observed"]
            if info_confirmed:
                states.append("information_confirmed")
            if candidate["exploration_ready"]:
                states.append("exploration_ready")
            for horizon in (1, 5):
                value = _close_forward_return(bars, signal_date, horizon)
                if value is None:
                    continue
                for state in states:
                    early_observations[spec["region"]][state][horizon].append({
                        "date": signal_date,
                        "ticker": ticker,
                        "return": value,
                        "state": candidate["state"],
                        "has_primary": bool(candidate["primary_event_ids"]),
                    })
    for market in observations.values():
        for horizon in HORIZONS:
            baseline_by_date = defaultdict(list)
            for row in market["setup_only"][horizon]:
                baseline_by_date[row["date"]].append(row["return"])
            baseline = {
                day: statistics.fmean(values) for day, values in baseline_by_date.items()
            }
            for variant in VARIANTS:
                for row in market[variant][horizon]:
                    row["excess_vs_setup"] = (
                        row["return"] - baseline[row["date"]]
                        if row["date"] in baseline else None
                    )
    metrics = {
        market: {
            variant: {
                f"t{horizon}": _summary(rows)
                for horizon, rows in horizons.items()
            }
            for variant, horizons in variants.items()
        }
        for market, variants in observations.items()
    }
    metrics["early_trend"] = {
        market: {
            state: {
                f"t{horizon}": _summary(rows)
                for horizon, rows in horizons.items()
            }
            for state, horizons in states.items()
        }
        for market, states in early_observations.items()
    }
    metrics["coverage"] = {
        **coverage,
        "authority_classifications": authority_counts,
        "information_grade": "retrospective_point_in_time_replay_only",
        "factor_grade": "retrospective_current_universe_survivorship_limited",
        "prospective_information_dates": sum(
            not row["backfill"] for row in news.values()
        ),
        "parameter_fit": "none_pre_registered_policy",
        "claim": "diagnostic_not_validated_alpha",
        "early_trend": {
            **early_coverage,
            "entry": "signal_session_close_for_measurement_only",
            "lookahead": "features_recomputed_at_each_snapshot_date; future closes used only for outcomes",
            "history_limit": "registered histories currently cover about 14 dates",
        },
    }
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-card", action="store_true")
    args = parser.parse_args(argv)
    config = _json(FACTOR_CONFIG)
    policy = _json(ALPHA_POLICY)
    news_policy = _json(NEWS_POLICY)
    # The early residual needs every curated peer, including names outside the
    # factor universe. Fetch the expanded taxonomy once; factor snapshots still
    # determine which economic exposures enter the replay.
    _, fetch_config = peer_residuals.build_taxonomy(config, _json(PEER_MAP))
    fetched = factors.fetch_universe(fetch_config)
    histories = (_jsonl(FACTOR_HISTORY), _jsonl(PEER_HISTORY), _jsonl(NEWS_HISTORY))
    metrics = evaluate(config, policy, news_policy, fetched, *histories)
    card_path = None
    if not args.no_card:
        inputs = []
        for path, source in (
            (FACTOR_HISTORY, "registered factor snapshots"),
            (PEER_HISTORY, "registered peer-residual snapshots"),
            (NEWS_HISTORY, "point-in-time news evidence snapshots"),
        ):
            rows = _jsonl(path)
            inputs.append({
                "symbol": path.name,
                "source": source,
                "bars": len(rows),
                "first_session": str((rows[0] if rows else {}).get("as_of")),
                "last_session": str((rows[-1] if rows else {}).get("as_of")),
                # 摘要必须覆盖被计数的那批行：拆出 archive 之后，工作文件
                # 只剩热窗，按文件字节取摘要会与 bars（完整序列）不同源。
                "digest": history_store.series_digest(path),
            })
        for spec in config["symbols"]:
            bars = (fetched.get(spec["ticker"]) or {}).get("bars") or []
            if bars:
                inputs.append({
                    "symbol": spec["ticker"],
                    "source": "Tencent qfq daily OHLC",
                    "bars": len(bars),
                    "first_session": bars[0]["date"],
                    "last_session": bars[-1]["date"],
                    "digest": run_card.series_digest(bars),
                })
        card_path = run_card.record(
            "add_alpha_walkforward",
            params={
                "horizons": list(HORIZONS),
                "entry": "production alpha_confirmation; next session; invalidation first; gap aware",
                "confirmation_window_sessions": policy["confirmation_window_sessions"],
                "variants": list(VARIANTS),
                "early_variants": ["observed", "information_confirmed", "exploration_ready"],
                "policy_version": add_alpha.POLICY_VERSION,
                "parameter_fit": "none; pre-registered thresholds",
            },
            inputs=inputs,
            metrics=metrics,
            code_files=[Path(__file__), Path(add_alpha.__file__), Path(early_trend.__file__)],
            notes=[
                "US and HK are ranked and evaluated separately.",
                "Production classify_authority and confirmation primitives are reused directly.",
                "Current-universe factor history is survivorship-limited and cannot validate authority.",
                "Legacy information replay seeds diagnostics only; prospective activation remains warming_up.",
                "Same-day entry/invalidation ambiguity is invalidated, never assumed filled.",
                "Early candidates are one row per underlying and use signal-date-close features with T+1/T+5 future closes only as outcomes.",
                "The early history is small; every result remains collecting/diagnostic, never validated alpha.",
            ],
        )
    print(json.dumps({"metrics": metrics, "run_card": str(card_path) if card_path else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
