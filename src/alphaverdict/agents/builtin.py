"""Independent deterministic reviewers used by the default council."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphaverdict.agents.base import AuditContext
from alphaverdict.audit.models import AgentReport, Finding, Severity
from alphaverdict.audit.statistics import (
    block_bootstrap,
    deflated_sharpe_probability,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    sign_flip_test,
)
from alphaverdict.data.bundle import DataBundle
from alphaverdict.engine.metrics import calculate_metrics
from alphaverdict.strategy.context import ResearchSnapshot


def _finding(
    agent: str,
    code: str,
    severity: Severity,
    title: str,
    evidence: str,
    recommendation: str,
    **metrics: Any,
) -> Finding:
    return Finding(code, severity, title, evidence, recommendation, agent, metrics)


class DataIntegrityAgent:
    name = "data-integrity"

    def review(self, context: AuditContext) -> AgentReport:
        prices = context.bundle.prices
        findings: list[Finding] = []
        high_bad = prices["high"] < prices[["open", "close", "low"]].max(axis=1)
        low_bad = prices["low"] > prices[["open", "close", "high"]].min(axis=1)
        nonpositive = (prices[["open", "high", "low", "close"]] <= 0).any(axis=1)
        negative_volume = prices["volume"].notna() & (prices["volume"] < 0)
        invalid_rows = int((high_bad | low_bad | nonpositive | negative_volume).sum())
        if invalid_rows:
            findings.append(
                _finding(
                    self.name,
                    "DATA_PRICE_INVARIANT",
                    Severity.CRITICAL,
                    "Price rows violate market invariants",
                    f"{invalid_rows} rows have impossible OHLC or volume values.",
                    "Repair the adapter mapping and rerun the complete pipeline.",
                    invalid_rows=invalid_rows,
                )
            )
        feature_leaks = int(
            (context.bundle.features["available_at"] < context.bundle.features["observed_at"]).sum()
        )
        if feature_leaks:
            findings.append(
                _finding(
                    self.name,
                    "DATA_TEMPORAL_LEAK",
                    Severity.CRITICAL,
                    "Features appear knowable before they were observed",
                    f"{feature_leaks} feature rows have available_at earlier than observed_at.",
                    "Correct availability timestamps; fiscal periods and publication dates are not interchangeable.",
                    rows=feature_leaks,
                )
            )
        metadata = context.bundle.metadata
        adjustment = str(metadata.get("price_adjustment", "unknown")).lower()
        if adjustment == "unknown":
            findings.append(
                _finding(
                    self.name,
                    "DATA_ADJUSTMENT_UNKNOWN",
                    Severity.HIGH,
                    "Price adjustment policy is undeclared",
                    "The bundle does not state whether splits and dividends are reflected.",
                    "Set metadata.price_adjustment and verify corporate-action handling against known cases.",
                )
            )
        survivorship = str(metadata.get("survivorship", "unknown")).lower()
        if context.bundle.universe.empty or survivorship not in {"point_in_time", "pit"}:
            findings.append(
                _finding(
                    self.name,
                    "DATA_SURVIVORSHIP_UNKNOWN",
                    Severity.HIGH,
                    "Point-in-time universe membership is not proven",
                    "No verified historical membership ledger establishes which stocks were eligible on each date.",
                    "Supply effective_from/effective_to membership rows and include delistings where relevant.",
                )
            )
        coverage = prices.groupby("symbol")["timestamp"].nunique()
        if not coverage.empty and coverage.min() < max(20, int(coverage.median() * 0.5)):
            findings.append(
                _finding(
                    self.name,
                    "DATA_COVERAGE_UNEVEN",
                    Severity.MEDIUM,
                    "History coverage varies sharply across stocks",
                    f"Shortest history is {int(coverage.min())} sessions versus median {int(coverage.median())}.",
                    "Explain listing dates and missing histories; avoid silently filling unavailable observations.",
                    minimum=int(coverage.min()),
                    median=int(coverage.median()),
                )
            )
        if str(metadata.get("data_classification", "")).lower() == "synthetic":
            findings.append(
                _finding(
                    self.name,
                    "DATA_SYNTHETIC",
                    Severity.INFO,
                    "Run uses demonstration data",
                    "Synthetic fixtures validate plumbing only and cannot support a market claim.",
                    "Repeat the run with licensed or user-owned real point-in-time data.",
                )
            )
        return AgentReport(
            self.name,
            f"Checked {len(prices):,} price rows and {len(context.bundle.features):,} feature rows.",
            tuple(findings),
            {"symbols": len(context.bundle.symbols), "invalid_price_rows": invalid_rows},
        )


class CausalityAgent:
    name = "causality"

    def review(self, context: AuditContext) -> AgentReport:
        sessions = pd.DatetimeIndex(
            context.bundle.prices["timestamp"].drop_duplicates().sort_values()
        )
        minimum = context.strategy.minimum_history
        candidates = sessions[minimum:-2] if len(sessions) > minimum + 2 else sessions[:0]
        findings: list[Finding] = []
        tested = 0
        reproducible = True
        prefix_stable = True
        warm_stable = True
        if len(candidates):
            positions = np.linspace(
                0,
                len(candidates) - 1,
                min(context.config.causality_cutoffs, len(candidates)),
                dtype=int,
            )
            for position in sorted({int(item) for item in positions}):
                cutoff = pd.Timestamp(candidates[position])
                original = ResearchSnapshot.from_bundle(context.bundle, cutoff)
                first = context.strategy.clone().screen(original).comparable()
                second = context.strategy.clone().screen(original).comparable()
                if not _same_signals(first, second):
                    reproducible = False
                perturbed = ResearchSnapshot.from_bundle(
                    _perturb_future(context.bundle, cutoff), cutoff
                )
                changed = context.strategy.clone().screen(perturbed).comparable()
                if not _same_signals(first, changed):
                    prefix_stable = False
                # Stale-warmup probe: a clone that already screened an earlier
                # snapshot must produce identical output here. Strategies that
                # freeze global state on first use fail this probe.
                earlier_position = max(0, position - 2)
                earlier = pd.Timestamp(candidates[earlier_position])
                warner = context.strategy.clone()
                _ = warner.screen(
                    ResearchSnapshot.from_bundle(context.bundle, earlier)
                ).comparable()
                warmed = warner.screen(original).comparable()
                if not _same_signals(first, warmed):
                    warm_stable = False
                tested += 1
        if not reproducible:
            findings.append(
                _finding(
                    self.name,
                    "STRATEGY_NONDETERMINISTIC",
                    Severity.CRITICAL,
                    "Repeated evaluations changed without new evidence",
                    "Independent strategy clones produced different scores for an identical snapshot.",
                    "Seed or remove randomness and external state before trusting comparisons.",
                )
            )
        if not prefix_stable:
            findings.append(
                _finding(
                    self.name,
                    "CAUSALITY_PREFIX_CHANGED",
                    Severity.CRITICAL,
                    "Past signals changed when future data was corrupted",
                    "At least one decision was not prefix-invariant under future perturbation.",
                    "Remove full-sample transforms, backward fills, and future-dependent global state.",
                )
            )
        if not warm_stable:
            findings.append(
                _finding(
                    self.name,
                    "STRATEGY_STATEFUL_WARMUP",
                    Severity.HIGH,
                    "Strategy output depends on evaluation order",
                    (
                        "A clone that screened an earlier snapshot produced different signals "
                        "at the same cutoff; frozen cross-decision state (lazy caches, "
                        "'first-call' globals) leaks between decisions."
                    ),
                    "Derive every score from the snapshot alone; reset or remove cached state "
                    "in screen(), never reuse statistics warmed on earlier data.",
                )
            )
        if tested == 0:
            findings.append(
                _finding(
                    self.name,
                    "CAUSALITY_UNTESTED",
                    Severity.HIGH,
                    "Sample is too short for prefix-invariance tests",
                    f"The strategy requires {minimum} sessions and no eligible cutoff remained.",
                    "Provide a longer history before accepting any causality claim.",
                )
            )
        return AgentReport(
            self.name,
            f"Ran reproducibility and future-perturbation checks at {tested} cutoffs.",
            tuple(findings),
            {"cutoffs": tested, "reproducible": reproducible, "prefix_stable": prefix_stable,
             "warm_stable": warm_stable},
        )


class RobustnessAgent:
    name = "robustness"

    def review(self, context: AuditContext) -> AgentReport:
        values = context.result.returns["strategy_return"].dropna()
        findings: list[Finding] = []
        folds = [
            part for part in np.array_split(values, context.config.stability_folds) if len(part)
        ]
        fold_returns = [float((1 + fold).prod() - 1) for fold in folds]
        positive_folds = sum(value > 0 for value in fold_returns)
        if len(folds) >= 2 and positive_folds < math.ceil(len(folds) / 2):
            findings.append(
                _finding(
                    self.name,
                    "FOLD_INSTABILITY",
                    Severity.HIGH,
                    "Most contiguous evaluation folds were not profitable",
                    f"{positive_folds} of {len(folds)} folds had positive total return.",
                    "Simplify the rule and pre-declare a fresh holdout before further tuning.",
                    fold_returns=fold_returns,
                )
            )
        bootstrap = block_bootstrap(
            values,
            simulations=context.config.bootstrap_simulations,
            block_size=context.config.bootstrap_block_size,
            confidence=context.config.confidence,
            seed=context.config.seed,
        )
        if bootstrap.get("probability_positive", 0.0) < context.config.confidence:
            findings.append(
                _finding(
                    self.name,
                    "BOOTSTRAP_UNCERTAIN",
                    Severity.MEDIUM,
                    "Bootstrap evidence is not decisive",
                    f"Probability of a positive resampled total return is {bootstrap.get('probability_positive', 0):.1%}.",
                    "Collect more independent periods and inspect the lower confidence path.",
                    **bootstrap,
                )
            )
        cost_curve: dict[str, float] = {}
        plan = context.engine.prepare(context.bundle, context.strategy.clone())
        base_commission = context.engine.config.commission_bps
        base_slippage = context.engine.config.slippage_bps
        for multiplier in context.config.cost_multipliers:
            stressed = context.engine.replay(
                plan,
                commission_bps=base_commission * multiplier,
                slippage_bps=base_slippage * multiplier,
            )
            cost_curve[f"{multiplier:g}x"] = float(stressed.metrics.get("total_return", 0.0) or 0.0)
        base = cost_curve.get("1x", float(context.result.metrics.get("total_return", 0.0) or 0.0))
        worst = cost_curve[f"{max(context.config.cost_multipliers):g}x"]
        if base > 0 and worst <= 0:
            findings.append(
                _finding(
                    self.name,
                    "COST_FRAGILE",
                    Severity.HIGH,
                    "Plausible friction erases the result",
                    f"Total return moves from {base:.1%} at configured costs to {worst:.1%} at the highest stress.",
                    "Reduce turnover or require a wider edge before accepting the strategy.",
                    cost_curve=cost_curve,
                )
            )
        benchmark = context.result.returns["benchmark_return"].dropna()
        regime_metrics: dict[str, Any] = {}
        if benchmark.empty:
            findings.append(
                _finding(
                    self.name,
                    "BENCHMARK_MISSING",
                    Severity.MEDIUM,
                    "Benchmark and regime evidence are unavailable",
                    "No point-in-time benchmark return series was supplied for the evaluated periods.",
                    "Configure a benchmark symbol present in the user-owned price data.",
                )
            )
        else:
            aligned = context.result.returns[["strategy_return", "benchmark_return"]].dropna()
            threshold = float(aligned["benchmark_return"].rolling(4, min_periods=2).std().median())
            high_vol = aligned["benchmark_return"].rolling(4, min_periods=2).std() > threshold
            labels = pd.Series(
                np.where(
                    high_vol, "high_vol", np.where(aligned["benchmark_return"] >= 0, "up", "down")
                ),
                index=aligned.index,
            )
            for label, rows in aligned.groupby(labels):
                regime_metrics[str(label)] = calculate_metrics(
                    rows["strategy_return"], periods_per_year=context.result.config.periods_per_year
                )
            totals = [
                float(item.get("total_return", 0.0) or 0.0) for item in regime_metrics.values()
            ]
            if len(totals) >= 2 and sum(value > 0 for value in totals) == 1:
                findings.append(
                    _finding(
                        self.name,
                        "REGIME_INSTABILITY",
                        Severity.MEDIUM,
                        "Performance is concentrated in one coarse regime",
                        "Only one evaluated benchmark regime had positive compounded return.",
                        "Treat regime dependence as a hypothesis and validate it on a fresh sample.",
                        regimes=regime_metrics,
                    )
                )
        return AgentReport(
            self.name,
            "Stressed contiguous folds, block-bootstrap paths, costs, and benchmark regimes.",
            tuple(findings),
            {
                "fold_returns": fold_returns,
                "bootstrap": bootstrap,
                "cost_curve": cost_curve,
                "regimes": regime_metrics,
            },
        )


class PerformanceAgent:
    name = "performance"

    def review(self, context: AuditContext) -> AgentReport:
        returns = context.result.returns
        findings: list[Finding] = []
        periods = len(returns)
        if periods < context.config.minimum_periods:
            findings.append(
                _finding(
                    self.name,
                    "PERFORMANCE_SAMPLE_SMALL",
                    Severity.MEDIUM,
                    "Performance summary rests on few rebalance periods",
                    f"Only {periods} hypothetical portfolio periods were evaluated.",
                    "Extend the requested date range or use a shorter pre-declared rebalance interval.",
                    periods=periods,
                )
            )
        sharpe = context.result.metrics.get("sharpe_ratio")
        if isinstance(sharpe, (int, float)) and abs(float(sharpe)) > 3:
            findings.append(
                _finding(
                    self.name,
                    "PERFORMANCE_EXTREME_SHARPE",
                    Severity.HIGH,
                    "Extreme Sharpe requires a mechanics audit",
                    f"Annualized Sharpe is {float(sharpe):.2f}, an outlier that often accompanies leakage or understated friction.",
                    "Verify timestamps, price adjustments, stale prices, and the complete number of attempted variants.",
                    sharpe=float(sharpe),
                )
            )
        gross_total = float(returns["gross_return"].sum())
        turnover_total = float(returns["turnover"].sum())
        breakeven_bps = gross_total / turnover_total * 10_000 if turnover_total > 0 else None
        configured_cost = context.result.config.total_cost_bps
        if breakeven_bps is not None and breakeven_bps <= configured_cost * 1.5:
            findings.append(
                _finding(
                    self.name,
                    "COST_FRAGILE",
                    Severity.HIGH,
                    "Gross edge sits close to configured friction",
                    f"Approximate breakeven friction is {breakeven_bps:.1f} bps versus {configured_cost:.1f} bps configured.",
                    "Reduce turnover or demonstrate a wider edge on untouched data.",
                    breakeven_bps=breakeven_bps,
                    configured_cost_bps=configured_cost,
                )
            )
        holdings = context.result.holdings
        symbol_concentration = 0.0
        if not holdings.empty:
            contributions = (
                (holdings["weight"] * holdings["period_return"])
                .groupby(holdings["symbol"])
                .sum()
                .abs()
            )
            if float(contributions.sum()) > 0:
                symbol_concentration = float(contributions.nlargest(3).sum() / contributions.sum())
            if symbol_concentration > 0.60:
                findings.append(
                    _finding(
                        self.name,
                        "SYMBOL_CONCENTRATION",
                        Severity.MEDIUM,
                        "A few stocks dominate absolute contribution",
                        f"The top three symbols contribute {symbol_concentration:.1%} of absolute gross contribution.",
                        "Repeat the evaluation without those symbols and inspect point-in-time universe breadth.",
                        top_three_share=symbol_concentration,
                    )
                )
        total_return = float(context.result.metrics.get("total_return", 0.0) or 0.0)
        benchmark_return = float(context.result.benchmark_metrics.get("total_return", 0.0) or 0.0)
        if context.result.config.benchmark_symbol and total_return < benchmark_return:
            findings.append(
                _finding(
                    self.name,
                    "BENCHMARK_UNDERPERFORMANCE",
                    Severity.LOW,
                    "Strategy underperformed its configured benchmark",
                    f"Net total return was {total_return:.1%} versus {benchmark_return:.1%} for the benchmark path.",
                    "Explain what risk or diversification benefit justifies the additional complexity.",
                    strategy_total_return=total_return,
                    benchmark_total_return=benchmark_return,
                )
            )
        return AgentReport(
            self.name,
            "Reviewed friction headroom, contribution concentration, benchmark context, and result scale.",
            tuple(findings),
            {
                "periods": periods,
                "breakeven_cost_bps": breakeven_bps,
                "top_three_symbol_contribution_share": symbol_concentration,
            },
        )


class StatisticalAgent:
    name = "statistics"

    def review(self, context: AuditContext) -> AgentReport:
        values = context.result.returns["strategy_return"].dropna()
        findings: list[Finding] = []
        psr = probabilistic_sharpe_ratio(values)
        dsr = deflated_sharpe_probability(values, context.config.n_trials)
        minimum_length = minimum_track_record_length(values, confidence=context.config.confidence)
        permutation = sign_flip_test(
            values, context.config.permutation_simulations, context.config.seed
        )
        if len(values) < context.config.minimum_periods or (
            minimum_length is not None and len(values) < minimum_length
        ):
            findings.append(
                _finding(
                    self.name,
                    "TRACK_RECORD_SHORT",
                    Severity.HIGH,
                    "Track record is shorter than the evidence threshold",
                    f"Observed {len(values)} periods; estimated minimum is {minimum_length if minimum_length is not None else 'not finite'}.",
                    "Extend the untouched out-of-sample history before drawing a conclusion.",
                    observed=len(values),
                    minimum=minimum_length,
                )
            )
        if context.config.n_trials > 1 and dsr < context.config.confidence:
            findings.append(
                _finding(
                    self.name,
                    "MULTIPLE_TESTING",
                    Severity.HIGH,
                    "The result does not clear its declared search burden",
                    f"Deflated Sharpe probability is {dsr:.1%} across {context.config.n_trials} declared trials.",
                    "Record all attempted variants and preserve a fresh final holdout.",
                    deflated_sharpe_probability=dsr,
                    n_trials=context.config.n_trials,
                )
            )
        if permutation["p_value"] > 1 - context.config.confidence:
            findings.append(
                _finding(
                    self.name,
                    "MEAN_NOT_SIGNIFICANT",
                    Severity.MEDIUM,
                    "Mean return is not distinguishable from a sign-flipped null",
                    f"Two-sided randomization p-value is {permutation['p_value']:.3f}.",
                    "Treat the edge as unproven and collect more independent observations.",
                    **permutation,
                )
            )
        contributions = values.abs().sort_values(ascending=False)
        concentration = (
            float(contributions.head(3).sum() / contributions.sum()) if contributions.sum() else 0.0
        )
        if concentration > 0.50:
            findings.append(
                _finding(
                    self.name,
                    "RETURN_CONCENTRATION",
                    Severity.HIGH,
                    "A few periods dominate absolute returns",
                    f"The three largest absolute periods contribute {concentration:.1%} of all absolute return movement.",
                    "Repeat the analysis without dominant periods and trace the responsible holdings.",
                    top_three_share=concentration,
                )
            )
        return AgentReport(
            self.name,
            "Measured Sharpe uncertainty, multiple-testing burden, randomization significance, and concentration.",
            tuple(findings),
            {
                "probabilistic_sharpe_ratio": psr,
                "deflated_sharpe_probability": dsr,
                "minimum_track_record_length": minimum_length,
                "sign_flip": permutation,
                "top_three_absolute_return_share": concentration,
            },
        )


class TrialsAgent:
    """Reconcile the declared search burden against the recorded trial ledger.

    Deflated Sharpe is only as honest as its ``n_trials`` input. This reviewer
    reads the project's hash-chained trial ledger — the automatic record of
    every variant actually run — and flags understated burdens, silent
    history, and tampered chains, so the multiple-testing penalty reflects
    evidence instead of self-report.
    """

    name = "trials"

    def __init__(self, ledger_path: str | None = None) -> None:
        self.ledger_path = ledger_path

    def review(self, context: AuditContext) -> AgentReport:
        findings: list[Finding] = []
        from alphaverdict.audit.ledger import TrialLedger  # noqa: PLC0415 - avoids import cycle

        path = Path(self.ledger_path) if self.ledger_path else _default_ledger_path()
        measurements: dict[str, Any] = {"ledger_path": str(path)}
        if not path.is_file():
            findings.append(
                _finding(
                    self.name,
                    "TRIALS_LEDGER_MISSING",
                    Severity.MEDIUM,
                    "No research diary records what was attempted",
                    f"No trial ledger exists at {path}; every run should append itself there.",
                    "Run `alphaverdict backtest` (auto-ledger) or `alphaverdict ledger note` "
                    "to start one; undeclared searches overstate confidence.",
                )
            )
            return AgentReport(self.name, "No trial ledger found.", tuple(findings), measurements)

        ledger = TrialLedger(path)
        intact, bad_index = ledger.verify()
        measurements["chain_intact"] = intact
        if not intact:
            findings.append(
                _finding(
                    self.name,
                    "TRIALS_LEDGER_TAMPERED",
                    Severity.CRITICAL,
                    "Trial ledger chain failed verification",
                    f"Hash chain broken at entry index {bad_index}; history was edited or truncated.",
                    "Restore the ledger from backup or restart it with a written note; "
                    "do not trust any verdict that depends on this history.",
                )
            )
            return AgentReport(self.name, "Ledger integrity check failed.", tuple(findings),
                               measurements)

        variants = ledger.trial_count()
        runs = ledger.run_count()
        names = ledger.variant_names()
        measurements.update({"distinct_variants": variants, "recorded_runs": runs,
                             "variants": names})
        declared = context.config.n_trials
        if variants > declared:
            findings.append(
                _finding(
                    self.name,
                    "TRIALS_UNDERDECLARED",
                    Severity.HIGH,
                    "Recorded search exceeds the declared trial burden",
                    f"Ledger shows {variants} distinct strategy variants across {runs} runs; "
                    f"audit config declares n_trials={declared}.",
                    "Raise audit.n_trials to the recorded count and re-read the deflated "
                    "Sharpe probability against the honest burden.",
                    recorded_variants=variants,
                    declared_n_trials=declared,
                )
            )
        elif variants < declared and runs > 0:
            findings.append(
                _finding(
                    self.name,
                    "TRIALS_OVERDECLARED",
                    Severity.INFO,
                    "Declared burden exceeds recorded trials",
                    f"n_trials={declared} but only {variants} distinct variants appear in the "
                    "ledger (unrecorded work elsewhere is possible).",
                    "If variants were tried outside this project, add a ledger note "
                    "describing them so the record matches reality.",
                )
            )
        return AgentReport(
            self.name,
            f"Verified {runs} chained runs across {variants} distinct variants "
            f"against declared n_trials={declared}.",
            tuple(findings),
            measurements,
        )


def _default_ledger_path() -> Path:
    return Path.cwd() / "trials.jsonl"


def _same_signals(first: pd.DataFrame, second: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(first, second, check_exact=True)
    except AssertionError:
        return False
    return True


def _perturb_future(bundle: DataBundle, cutoff: pd.Timestamp) -> DataBundle:
    prices = bundle.prices.copy()
    mask = prices["timestamp"] > cutoff
    if mask.any():
        factors = 1.5 + np.arange(int(mask.sum()), dtype=float) / max(1, int(mask.sum()))
        for column in ("open", "high", "low", "close"):
            prices.loc[mask, column] = prices.loc[mask, column].to_numpy(dtype=float) * factors
        prices.loc[mask, "volume"] = prices.loc[mask, "volume"].to_numpy(dtype=float) * 3
    features = bundle.features.copy()
    future_features = features["available_at"] > cutoff
    for index in features.index[future_features]:
        value = features.at[index, "value"]
        features.at[index, "value"] = (
            float(value) * -7 if isinstance(value, (int, float)) else "future-corrupted"
        )
    events = bundle.events.copy()
    future_events = events["available_at"] > cutoff
    for index in events.index[future_events]:
        events.at[index, "payload"] = {"future_corrupted": True}
    # Bundle metadata is NOT temporally governed, so strategies must never derive
    # scores from it. Corrupting it here enforces that rule mechanically: any
    # strategy whose signals move with metadata values is leaking non-point-in-time
    # state and deserves the prefix-changed finding.
    return DataBundle(
        prices,
        features,
        events,
        bundle.universe,
        _corrupt_metadata(bundle.metadata),
    )


def _corrupt_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    def corrupt(value: Any) -> Any:
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return float(value) * -7.0
        if isinstance(value, str):
            return f"{value}-future-corrupted"
        if isinstance(value, dict):
            return {key: corrupt(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [corrupt(item) for item in value]
        return value

    return {key: corrupt(item) for key, item in metadata.items()}
