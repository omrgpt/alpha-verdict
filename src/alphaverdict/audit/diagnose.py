"""Deterministic strategy diagnosis: measurements in, ranked experiments out.

The council's findings say *whether* a result deserves trust; the diagnostician
says *what to do next about this specific strategy*. Every rule reads the run's
own evidence — contribution tables, cost curves, fold returns, regime splits,
benchmark gaps — and prescribes one concrete re-run plus how to interpret both
outcomes. Pure arithmetic over measured data: same inputs, same prescriptions.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

from alphaverdict.audit.models import Finding, Severity, StrategyExperiment
from alphaverdict.engine.models import BacktestResult


class _Rule:
    """One diagnosis: fires when its trigger codes appear; reads live metrics."""

    def __init__(
        self,
        triggers: set[str],
        builder: Callable[[BacktestResult], dict[str, Any] | None],
        severity: Severity,
    ) -> None:
        self._triggers = triggers
        self._builder = builder
        self._severity = severity

    def build(self, result: BacktestResult, codes: set[str]) -> StrategyExperiment | None:
        triggered = sorted(self._triggers & codes)
        if not triggered:
            return None
        payload = self._builder(result)
        if payload is None:
            return None
        return StrategyExperiment(
            rank=0,
            severity=self._severity,
            source_codes=tuple(triggered),
            **payload,
        )


def diagnose(
    result: BacktestResult,
    findings: tuple[Finding, ...],
) -> tuple[StrategyExperiment, ...]:
    """Rank evidence-backed next experiments for one evaluated strategy."""
    codes = {finding.code for finding in findings}
    rules: tuple[_Rule, ...] = (
        _concentration_rule(),
        _cost_fragility_rule(),
        _fold_instability_rule(),
        _regime_dependence_rule(),
        _turnover_rule(),
        _benchmark_gap_rule(),
        _short_track_rule(),
        _extreme_sharpe_rule(),
    )
    experiments = [
        experiment for rule in rules if (experiment := rule.build(result, codes)) is not None
    ]
    # Rank 1 = most urgent: highest severity first; ties keep rule definition
    # order (sorts are stable), so identical inputs always produce identical ranks.
    experiments.sort(key=lambda item: item.severity, reverse=True)
    return tuple(replace_rank(item, position) for position, item in enumerate(experiments, start=1))


def strengths_of(result: BacktestResult, findings: tuple[Finding, ...]) -> tuple[str, ...]:
    """Name what measurably went RIGHT, so verdicts are balanced, not scaremongering."""
    strengths: list[str] = []
    codes = {finding.code for finding in findings}
    if "CAUSALITY_PREFIX_CHANGED" not in codes and "STRATEGY_NONDETERMINISTIC" not in codes:
        strengths.append(
            "Signals are causally clean: repeated evaluation and future-data corruption "
            "left decisions unchanged."
        )
    sharpe = float(result.metrics.get("sharpe_ratio") or 0.0)
    if 0.5 <= sharpe <= 2.5:
        strengths.append(
            f"Sharpe of {sharpe:.2f} sits in a plausible band for a real, repeatable rule."
        )
    benchmark = float(result.benchmark_metrics.get("total_return") or 0.0)
    total = float(result.metrics.get("total_return") or 0.0)
    if math.isfinite(benchmark) and math.isfinite(total) and total > benchmark:
        strengths.append(f"Beat its benchmark by {_pct(total - benchmark)} over the window.")
    annual = float(result.metrics.get("annual_turnover") or 0.0)
    if 0 < annual <= 6:
        strengths.append(f"Trading pace (~{annual:.1f}x/year) keeps costs secondary to skill.")
    return tuple(strengths)


def replace_rank(item: StrategyExperiment, rank: int) -> StrategyExperiment:
    return StrategyExperiment(
        rank=rank,
        title=item.title,
        observation=item.observation,
        experiment=item.experiment,
        rationale=item.rationale,
        source_codes=item.source_codes,
        severity=item.severity,
    )


def _pct(value: float) -> str:
    return f"{value:.1%}"


# --------------------------------------------------------------------- rules


def _concentration_rule() -> _Rule:
    def build(result: BacktestResult) -> dict[str, Any] | None:
        holdings = result.holdings
        if holdings.empty:
            return None
        contributions = (
            (holdings["weight"] * holdings["period_return"])
            .groupby(holdings["symbol"])
            .sum()
            .abs()
            .sort_values(ascending=False)
        )
        total = float(contributions.sum())
        if total <= 0:
            return None
        top = contributions.head(3)
        share = float(top.sum() / total)
        names = ", ".join(str(symbol) for symbol in top.index[:3])
        return {
            "title": "Test dependence on your three biggest contributors",
            "observation": (
                f"{names} drive {_pct(share)} of absolute profit contribution across "
                f"{int(holdings['symbol'].nunique())} symbols held."
            ),
            "experiment": (
                "Re-run with those symbols excluded from eligibility (denylist them in "
                "your strategy's score()). Compare total return and Sharpe side by side."
            ),
            "rationale": (
                "If the edge survives without them it is broad and repeatable; if it "
                "vanishes, the result was concentration luck on a few tickers, not a "
                "repeatable rule."
            ),
        }

    return _Rule({"SYMBOL_CONCENTRATION", "RETURN_CONCENTRATION"}, build, Severity.HIGH)


def _cost_fragility_rule() -> _Rule:
    def build(result: BacktestResult) -> dict[str, Any] | None:
        returns = result.returns
        gross_total = float(returns["gross_return"].sum())
        turnover_total = float(returns["turnover"].sum())
        if returns.empty or turnover_total <= 0:
            return None
        breakeven_bps = gross_total / turnover_total * 10_000
        configured = result.config.total_cost_bps
        headroom = breakeven_bps / configured if configured > 0 else math.inf
        annual_turnover = float(result.metrics.get("annual_turnover") or 0.0)
        detail = (
            f"Gross edge per unit traded is ~{breakeven_bps:.1f} bps against "
            f"{configured:.1f} bps configured costs ({headroom:.1f}x headroom); "
            f"the book turns over ~{annual_turnover:.1f}x per year."
        )
        prescription = (
            f"Re-run with combined commission+slippage set to {breakeven_bps:.0f} bps "
            "(the measured breakeven), then once more at half that."
            if headroom < 2
            else "Re-run once at 3x current costs to confirm the margin is real."
        )
        reading = (
            "An edge surviving 3x costs is robust to execution reality; one that dies "
            "before breakeven was never tradeable research — only a simulation artifact."
        )
        return {
            "title": "Stress your edge against execution costs at the measured breakeven",
            "observation": detail,
            "experiment": prescription,
            "rationale": reading,
        }

    return _Rule({"COST_FRAGILE"}, build, Severity.HIGH)


def _fold_instability_rule() -> _Rule:
    def build(result: BacktestResult) -> dict[str, Any] | None:
        values = result.returns["strategy_return"].dropna()
        if len(values) < 8:
            return None
        folds = [part for part in np.array_split(values.to_numpy(), 4) if len(part)]
        fold_returns = [float((1 + fold).prod() - 1) for fold in folds]
        positive = sum(value > 0 for value in fold_returns)
        losing = [_pct(value) for value in fold_returns if value <= 0]
        detail = f"Split into quarters, {positive}/4 compounded positively" + (
            f"; losing windows: {', '.join(losing)}." if losing else "."
        )
        return {
            "title": "Check whether profits come from one lucky window",
            "observation": detail,
            "experiment": (
                "Run `alphaverdict walkforward --train 26 --test 13 --embargo 2`, then "
                "read pooled out-of-sample Sharpe against the in-sample Sharpe."
            ),
            "rationale": (
                "A real rule keeps working on untouched later data. If OOS Sharpe "
                "retains under half of in-sample, treat the backtest as a description "
                "of the past, not a property of the strategy."
            ),
        }

    return _Rule({"FOLD_INSTABILITY", "REGIME_INSTABILITY"}, build, Severity.HIGH)


def _regime_dependence_rule() -> _Rule:
    def build(result: BacktestResult) -> dict[str, Any] | None:
        aligned = result.returns[["strategy_return", "benchmark_return"]].dropna()
        if len(aligned) < 12:
            return None
        labels = np.where(aligned["benchmark_return"] >= 0, "up-market", "down-market")
        totals = {
            str(label): float((1 + rows["strategy_return"]).prod() - 1)
            for label, rows in aligned.groupby(labels)
        }
        winners = [name for name, value in totals.items() if value > 0]
        losers = [name for name, value in totals.items() if value <= 0]
        if len(winners) != 1 or not losers:
            return None
        breakdown = ", ".join(f"{name} {_pct(value)}" for name, value in totals.items())
        return {
            "title": f"Profits may exist only in {winners[0]} periods",
            "observation": f"Total return by regime: {breakdown}.",
            "experiment": (
                "Extend the window until losing regimes are well represented, then "
                "re-run; alternatively add an explicit regime gate and compare verdicts."
            ),
            "rationale": (
                "An edge that only appears when everything rises is market beta wearing "
                "a costume. Durable rules survive both regimes or gate themselves."
            ),
        }

    return _Rule({"REGIME_INSTABILITY"}, build, Severity.MEDIUM)


def _slower_rebalance(times_per_year: int) -> str:
    if times_per_year <= 2:
        return "monthly"
    if times_per_year <= 13:
        return "weekly"
    return "daily"


def _turnover_rule() -> _Rule:
    def build(result: BacktestResult) -> dict[str, Any] | None:
        annual = float(result.metrics.get("annual_turnover") or 0.0)
        if annual <= 0:
            return None
        target = max(1, round(annual / 4))
        return {
            "title": "Test whether slower trading keeps the edge",
            "observation": (
                f"The portfolio trades ~{annual:.1f}x its value per year; every turn "
                "pays friction before any skill is proven."
            ),
            "experiment": (
                f"Re-run with rebalance={_slower_rebalance(target)} (~{target} turns/year "
                "target), holding everything else identical."
            ),
            "rationale": (
                "If most of the return survives at a quarter of the pace, you keep the "
                "edge and shed most cost risk. If it collapses, the strategy was "
                "harvesting short-term noise that rarely survives real execution."
            ),
        }

    return _Rule({"COST_FRAGILE", "PERFORMANCE_EXTREME_SHARPE"}, build, Severity.MEDIUM)


def _benchmark_gap_rule() -> _Rule:
    def build(result: BacktestResult) -> dict[str, Any] | None:
        total = float(result.metrics.get("total_return") or 0.0)
        bench = float(result.benchmark_metrics.get("total_return") or 0.0)
        if not (math.isfinite(total) and math.isfinite(bench)) or total >= bench:
            return None
        return {
            "title": "Close the gap against simply holding the benchmark",
            "observation": (
                f"The strategy returned {_pct(total)} versus {_pct(bench)} for its "
                f"benchmark — underperformance of {_pct(bench - total)}."
            ),
            "experiment": (
                "Re-run with top_k doubled (broader book). If the shortfall shrinks, "
                "the narrow selection is adding noise rather than alpha."
            ),
            "rationale": (
                "Every strategy must justify its complexity against the index. Broader "
                "selection isolates whether the ranking layer helps or hurts."
            ),
        }

    return _Rule({"BENCHMARK_UNDERPERFORMANCE"}, build, Severity.LOW)


def _short_track_rule() -> _Rule:
    minimum = 24

    def build(result: BacktestResult) -> dict[str, Any] | None:
        periods = int(result.metrics.get("periods") or len(result.returns))
        return {
            "title": "Extend history before believing anything here",
            "observation": f"Only {periods} rebalance periods were evaluated.",
            "experiment": (
                "Request at least 3x more history (earlier request.start) and compare "
                "verdicts. Same code, longer memory."
            ),
            "rationale": (
                "Short samples flatter weak ideas and bury strong ones. Verdicts on "
                f"under {minimum} periods are provisional by construction."
            ),
        }

    return _Rule({"PERFORMANCE_SAMPLE_SMALL", "TRACK_RECORD_SHORT"}, build, Severity.MEDIUM)


def _extreme_sharpe_rule() -> _Rule:
    def build(result: BacktestResult) -> dict[str, Any] | None:
        sharpe = float(result.metrics.get("sharpe_ratio") or 0.0)
        return {
            "title": "Audit an implausibly high Sharpe before celebrating",
            "observation": (
                f"Annualized Sharpe is {sharpe:.2f}; world-class funds rarely sustain >2."
            ),
            "experiment": (
                "Cap single-period price moves above 20% and re-run. If Sharpe stays "
                "extreme, inspect timestamps and adjustment handling next."
            ),
            "rationale": (
                "Extreme ratios almost always trace to data artifacts — stale prices, "
                "split errors, leakage — not skill. This test localizes which."
            ),
        }

    return _Rule({"PERFORMANCE_EXTREME_SHARPE"}, build, Severity.HIGH)
