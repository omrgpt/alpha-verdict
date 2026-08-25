"""Causal open-to-open portfolio research backtester."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from alphaverdict._version import __version__
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.technicals import open_matrix
from alphaverdict.engine.costs import friction, portfolio_turnover
from alphaverdict.engine.metrics import calculate_metrics
from alphaverdict.engine.models import BacktestConfig, BacktestResult, Weighting
from alphaverdict.engine.schedule import decision_dates, next_session
from alphaverdict.exceptions import InsufficientDataError
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot
from alphaverdict.utils import canonical_json, sha256_text


@dataclass(frozen=True)
class ReplayPlan:
    """Cost-independent research state computed once per bundle and strategy.

    Screens, selections, holdings, and period gross returns never depend on
    commission or slippage assumptions, so the expensive snapshot work happens
    exactly once and every cost variant replays in pure arithmetic.
    """

    config: BacktestConfig
    strategy_name: str
    strategy_fingerprint: str
    data_fingerprint: str
    periods: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    warnings: frozenset[str] = field(default_factory=frozenset)


class BacktestEngine:
    """Evaluate rankings as hypothetical long-only portfolios; never place orders."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, bundle: DataBundle, strategy: StockStrategy) -> BacktestResult:
        """Prepare cost-independent state once, then replay at configured costs."""
        return self.replay(self.prepare(bundle, strategy))

    def prepare(self, bundle: DataBundle, strategy: StockStrategy) -> ReplayPlan:
        """Run every snapshot, screen, and selection exactly once."""
        if bundle.prices.empty:
            raise InsufficientDataError("backtesting requires canonical daily prices")
        price_opens = open_matrix(bundle.prices)
        sessions = pd.DatetimeIndex(price_opens.index).sort_values()
        start = _utc(self.config.start) if self.config.start is not None else None
        end = _utc(self.config.end) if self.config.end is not None else None
        decisions = decision_dates(sessions, self.config.rebalance, start=start, end=end)
        schedule = [(date, next_session(sessions, date)) for date in decisions]
        schedule = [
            (decision, execution) for decision, execution in schedule if execution is not None
        ]
        if len(schedule) < 2:
            raise InsufficientDataError("backtest needs at least two executable rebalance periods")

        warnings: set[str] = {
            "Results are research simulations, not investment advice or execution instructions.",
            "Signals are formed after a decision close and applied at the following session open.",
        }
        periods: list[dict[str, Any]] = []

        for index in range(len(schedule) - 1):
            decision, execution = schedule[index]
            _, next_execution = schedule[index + 1]
            snapshot = ResearchSnapshot.from_bundle(bundle, decision)
            signals = strategy.screen(snapshot)
            selected = signals.top(self.config.top_k, minimum_score=self.config.minimum_score)
            signal_rows = [
                {
                    "decision_at": decision,
                    "symbol": row.symbol,
                    "score": float(row.score),
                    "eligible": bool(row.eligible),
                    "rationale": row.rationale,
                }
                for row in selected.itertuples(index=False)
            ]
            weights = self._weights(selected)
            valid = self._valid_returns(price_opens, weights, execution, next_execution)
            dropped = set(weights) - set(valid)
            if dropped:
                warnings.add(
                    "Some selected stocks lacked valid execution prices and were left in cash."
                )
            effective = {symbol: weights[symbol] for symbol in valid}
            gross = sum(effective[symbol] * valid[symbol] for symbol in effective)
            periods.append(
                {
                    "decision_at": decision,
                    "execution_at": execution,
                    "exit_at": next_execution,
                    "gross_return": gross,
                    "benchmark_return": self._benchmark_return(
                        price_opens, execution, next_execution
                    ),
                    "weights": effective,
                    "returns_by_symbol": valid,
                    "gross_exposure": sum(effective.values()),
                    "holdings_count": len(effective),
                    "signal_rows": signal_rows,
                    "scores": selected.set_index("symbol")["score"].to_dict(),
                }
            )

        return ReplayPlan(
            config=self.config,
            strategy_name=strategy.name,
            strategy_fingerprint=strategy.fingerprint(),
            data_fingerprint=bundle.fingerprint(),
            periods=tuple(periods),
            warnings=frozenset(warnings),
        )

    def replay(
        self,
        plan: ReplayPlan,
        *,
        commission_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> BacktestResult:
        """Rebuild full results from a prepared plan under one cost assumption."""
        config = self.config
        if commission_bps is not None or slippage_bps is not None:
            config = replace(
                plan.config,
                commission_bps=plan.config.commission_bps
                if commission_bps is None
                else commission_bps,
                slippage_bps=plan.config.slippage_bps if slippage_bps is None else slippage_bps,
            )
        total_cost_bps = config.commission_bps + config.slippage_bps

        return_rows: list[dict[str, Any]] = []
        holding_rows: list[dict[str, Any]] = []
        signal_rows: list[dict[str, Any]] = []
        previous: dict[str, float] = {}

        for period in plan.periods:
            weights: dict[str, float] = period["weights"]
            valid: dict[str, float] = period["returns_by_symbol"]
            turnover = portfolio_turnover(previous, weights)
            cost = friction(turnover, total_cost_bps)
            net = period["gross_return"] - cost
            execution = period["execution_at"]
            return_rows.append(
                {
                    "timestamp": period["exit_at"],
                    "decision_at": period["decision_at"],
                    "execution_at": execution,
                    "gross_return": period["gross_return"],
                    "cost": cost,
                    "strategy_return": net,
                    "benchmark_return": period["benchmark_return"],
                    "turnover": turnover,
                    "gross_exposure": period["gross_exposure"],
                    "holdings_count": period["holdings_count"],
                }
            )
            scores: dict[str, float] = period["scores"]
            for symbol, weight in weights.items():
                holding_rows.append(
                    {
                        "execution_at": execution,
                        "exit_at": period["exit_at"],
                        "symbol": symbol,
                        "weight": weight,
                        "score": float(scores[symbol]),
                        "period_return": valid[symbol],
                    }
                )
            signal_rows.extend(period["signal_rows"])
            previous = self._drifted_weights(weights, valid)

        returns = pd.DataFrame(return_rows).set_index("timestamp").sort_index()
        strategy_equity = config.initial_capital * (1 + returns["strategy_return"]).cumprod()
        benchmark_equity = (
            config.initial_capital * (1 + returns["benchmark_return"].fillna(0)).cumprod()
        )
        equity = pd.DataFrame({"strategy": strategy_equity, "benchmark": benchmark_equity})
        metrics = calculate_metrics(
            returns["strategy_return"],
            periods_per_year=config.periods_per_year,
            annual_risk_free_rate=config.annual_risk_free_rate,
            benchmark=returns["benchmark_return"],
            turnover=returns["turnover"],
            exposure=returns["gross_exposure"],
        )
        benchmark_metrics = calculate_metrics(
            returns["benchmark_return"],
            periods_per_year=config.periods_per_year,
            annual_risk_free_rate=config.annual_risk_free_rate,
        )
        manifest = self._manifest(config, plan, returns)
        return BacktestResult(
            config=config,
            strategy_name=plan.strategy_name,
            strategy_fingerprint=plan.strategy_fingerprint,
            data_fingerprint=plan.data_fingerprint,
            returns=returns,
            equity=equity,
            holdings=pd.DataFrame(holding_rows),
            signals=pd.DataFrame(signal_rows),
            metrics=metrics,
            benchmark_metrics=benchmark_metrics,
            warnings=tuple(sorted(plan.warnings)),
            manifest=manifest,
        )

    def with_cost_multiplier(self, multiplier: float) -> BacktestEngine:
        if multiplier < 0:
            raise ValueError("cost multiplier must be non-negative")
        return BacktestEngine(
            replace(
                self.config,
                commission_bps=self.config.commission_bps * multiplier,
                slippage_bps=self.config.slippage_bps * multiplier,
            )
        )

    def _weights(self, selected: pd.DataFrame) -> dict[str, float]:
        if selected.empty:
            return {}
        count = len(selected)
        if self.config.weighting is Weighting.EQUAL:
            raw = pd.Series(1.0, index=selected["symbol"])
        elif self.config.weighting is Weighting.RANK:
            raw = pd.Series(np.arange(count, 0, -1, dtype=float), index=selected["symbol"])
        else:
            scores = selected.set_index("symbol")["score"].astype(float)
            raw = (scores - scores.min()).clip(lower=0) + 1e-12
        normalized = raw / raw.sum()
        capped = normalized.clip(upper=self.config.max_weight)
        return {str(symbol): float(weight) for symbol, weight in capped.items() if weight > 0}

    @staticmethod
    def _valid_returns(
        prices: pd.DataFrame,
        weights: Mapping[str, float],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        for symbol in weights:
            if symbol not in prices or start not in prices.index or end not in prices.index:
                continue
            entry = prices.at[start, symbol]
            exit_price = prices.at[end, symbol]
            if (
                pd.notna(entry)
                and pd.notna(exit_price)
                and float(entry) > 0
                and float(exit_price) > 0
            ):
                result[symbol] = float(exit_price / entry - 1)
        return result

    @staticmethod
    def _drifted_weights(
        starting: Mapping[str, float], period_returns: Mapping[str, float]
    ) -> dict[str, float]:
        """Mark target weights to the next execution before measuring new turnover."""
        cash = max(0.0, 1.0 - sum(starting.values()))
        ending_values = {
            symbol: weight * (1 + period_returns[symbol])
            for symbol, weight in starting.items()
            if symbol in period_returns
        }
        total = cash + sum(ending_values.values())
        if total <= 0:
            return {}
        return {symbol: value / total for symbol, value in ending_values.items() if value > 0}

    def _benchmark_return(
        self, prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
    ) -> float:
        symbol = self.config.benchmark_symbol
        if not symbol or symbol not in prices:
            return float("nan")
        entry = prices.at[start, symbol]
        exit_price = prices.at[end, symbol]
        if pd.isna(entry) or pd.isna(exit_price) or float(entry) <= 0:
            return float("nan")
        return float(exit_price / entry - 1)

    def _manifest(
        self, config: BacktestConfig, plan: ReplayPlan, returns: pd.DataFrame
    ) -> dict[str, Any]:
        config_payload = {
            "rebalance": config.rebalance.value,
            "top_k": config.top_k,
            "minimum_score": config.minimum_score,
            "weighting": config.weighting.value,
            "max_weight": config.max_weight,
            "commission_bps": config.commission_bps,
            "slippage_bps": config.slippage_bps,
            "benchmark_symbol": config.benchmark_symbol,
            "seed": config.seed,
        }
        content = {
            "schema_version": "1",
            "alphaverdict_version": __version__,
            "data_fingerprint": plan.data_fingerprint,
            "strategy_fingerprint": plan.strategy_fingerprint,
            "config_fingerprint": sha256_text(canonical_json(config_payload)),
            "periods": len(returns),
            "result_fingerprint": sha256_text(
                returns.to_json(date_format="iso", double_precision=15)
            ),
        }
        content["run_id"] = sha256_text(canonical_json(content))[:16]
        return content


def _utc(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
