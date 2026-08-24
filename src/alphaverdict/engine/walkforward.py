"""Deterministic walk-forward evaluation with embargoed contiguous folds.

Walk-forward analysis answers the question single-sample backtests cannot: does
the edge persist on untouched, later data? Folds are contiguous, never shuffled,
and separated by an embargo gap so labels near the split cannot leak into the
training window through overlapping holding periods.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import pandas as pd

from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.metrics import calculate_metrics
from alphaverdict.engine.schedule import decision_dates
from alphaverdict.exceptions import InsufficientDataError
from alphaverdict.strategy.base import StockStrategy


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    """Bounded settings for contiguous, embargoed walk-forward folds.

    All three durations are counted in rebalance periods, matching the units of
    ``BacktestConfig.rebalance``, so weekly rebalances count weeks.
    """

    train_periods: int = 52
    test_periods: int = 13
    embargo_periods: int = 2

    def __post_init__(self) -> None:
        if self.train_periods < 4:
            raise ValueError("walk-forward needs at least 4 training periods")
        if self.test_periods < 2:
            raise ValueError("walk-forward needs at least 2 testing periods")
        if self.embargo_periods < 0:
            raise ValueError("embargo_periods must be non-negative")


@dataclass(frozen=True)
class WalkForwardFold:
    """One contiguous in-sample/out-of-sample pair."""

    index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_periods: int
    test_periods: int
    train_total_return: float
    test_total_return: float
    train_sharpe: float
    test_sharpe: float
    test_max_drawdown: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "train_periods": self.train_periods,
            "test_periods": self.test_periods,
            "train_total_return": self.train_total_return,
            "test_total_return": self.test_total_return,
            "train_sharpe": self.train_sharpe,
            "test_sharpe": self.test_sharpe,
            "test_max_drawdown": self.test_max_drawdown,
        }


@dataclass(frozen=True)
class WalkForwardResult:
    """Merged walk-forward evidence with degradation findings."""

    strategy_name: str
    config: WalkForwardConfig
    folds: tuple[WalkForwardFold, ...]
    pooled_oos_metrics: dict[str, float | int | None]
    mean_train_sharpe: float
    pooled_oos_sharpe: float
    degradation_ratio: float | None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def verdict_hint(self) -> str:
        if self.degradation_ratio is None:
            return "inconclusive"
        if any(item.test_total_return <= 0 for item in self.folds):
            return "fragile"
        if (
            len(self.folds) >= 2
            and sum(item.test_total_return > 0 for item in self.folds) < (len(self.folds) + 1) // 2
        ):
            return "fragile"
        if self.degradation_ratio < 0.5:
            return "degraded"
        return "consistent"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy_name,
            "config": {
                "train_periods": self.config.train_periods,
                "test_periods": self.config.test_periods,
                "embargo_periods": self.config.embargo_periods,
            },
            "verdict_hint": self.verdict_hint,
            "mean_train_sharpe": self.mean_train_sharpe,
            "pooled_oos_sharpe": self.pooled_oos_sharpe,
            "degradation_ratio": self.degradation_ratio,
            "pooled_oos_metrics": self.pooled_oos_metrics,
            "folds": [fold.to_dict() for fold in self.folds],
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }


def _segment_returns(
    bundle: Any,
    strategy: StockStrategy,
    base_engine: BacktestEngine,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.Series:
    segment_config = replace(base_engine.config, start=start, end=end)
    result = BacktestEngine(segment_config).run(bundle, strategy.clone())
    return result.returns["strategy_return"].dropna()


def _sharpe_of(values: pd.Series) -> float:
    clean = values.dropna()
    if len(clean) < 2 or float(clean.std(ddof=1)) == 0:
        return 0.0
    return float(clean.mean() / clean.std(ddof=1))


def walk_forward(
    bundle: Any,
    strategy: StockStrategy,
    engine: BacktestEngine,
    config: WalkForwardConfig | None = None,
) -> WalkForwardResult:
    """Evaluate one strategy across embargoed contiguous folds."""
    settings = config or WalkForwardConfig()
    if bundle.prices.empty:
        raise InsufficientDataError("walk-forward requires canonical daily prices")
    sessions = pd.DatetimeIndex(sorted(set(bundle.prices["timestamp"]))).sort_values()
    all_decisions = decision_dates(sessions, engine.config.rebalance)
    needed = settings.train_periods + settings.embargo_periods + settings.test_periods
    if len(all_decisions) < needed * 2:
        raise InsufficientDataError(
            f"walk-forward needs at least {needed * 2} rebalance decisions "
            f"({settings.train_periods} train + {settings.embargo_periods} embargo + "
            f"{settings.test_periods} test per fold, two folds minimum); found {len(all_decisions)}"
        )

    folds: list[WalkForwardFold] = []
    oos_returns: list[pd.Series] = []
    warnings: set[str] = {
        "Walk-forward evidence is hypothetical research output, never an execution instruction.",
    }
    notes: list[str] = []
    cursor = 0

    while cursor + needed <= len(all_decisions):
        train_slice = all_decisions[cursor : cursor + settings.train_periods]
        test_slice = all_decisions[
            cursor + settings.train_periods + settings.embargo_periods : cursor
            + settings.train_periods
            + settings.embargo_periods
            + settings.test_periods
        ]
        if len(test_slice) < settings.test_periods:
            break
        try:
            train_returns = _segment_returns(
                bundle, strategy, engine, train_slice[0], train_slice[-1]
            )
            test_returns = _segment_returns(bundle, strategy, engine, test_slice[0], test_slice[-1])
        except InsufficientDataError:
            notes.append(f"fold {len(folds)} skipped: too few executable periods")
            cursor += settings.test_periods
            continue

        def total(values: pd.Series) -> float:
            return float((1 + values.dropna()).prod() - 1) if not values.empty else 0.0

        fold = WalkForwardFold(
            index=len(folds),
            train_start=pd.Timestamp(train_slice[0]),
            train_end=pd.Timestamp(train_slice[-1]),
            test_start=pd.Timestamp(test_slice[0]),
            test_end=pd.Timestamp(test_slice[-1]),
            train_periods=len(train_returns),
            test_periods=len(test_returns),
            train_total_return=total(train_returns),
            test_total_return=total(test_returns),
            train_sharpe=_sharpe_of(train_returns),
            test_sharpe=_sharpe_of(test_returns),
            test_max_drawdown=_drawdown(test_returns),
        )
        folds.append(fold)
        oos_returns.append(test_returns)
        cursor += settings.test_periods

    if len(folds) < 2:
        raise InsufficientDataError(
            "walk-forward produced fewer than two complete folds; extend the history"
        )

    pooled = pd.concat(oos_returns).sort_index()
    pooled_metrics = calculate_metrics(
        pooled,
        periods_per_year=engine.config.periods_per_year,
        annual_risk_free_rate=engine.config.annual_risk_free_rate,
    )
    mean_train = float(sum(fold.train_sharpe for fold in folds) / len(folds))
    pooled_sharpe = _sharpe_of(pooled)
    degradation: float | None = None
    if abs(mean_train) > 1e-9:
        degradation = pooled_sharpe / mean_train

    if degradation is not None and degradation < 0.5:
        warnings.add(f"Out-of-sample Sharpe retains only {degradation:.0%} of in-sample Sharpe.")
    positive_tests = sum(1 for fold in folds if fold.test_total_return > 0)
    if positive_tests < (len(folds) + 1) // 2:
        warnings.add(
            f"Only {positive_tests} of {len(folds)} out-of-sample folds compounded positively."
        )

    return WalkForwardResult(
        strategy_name=strategy.name,
        config=settings,
        folds=tuple(folds),
        pooled_oos_metrics=pooled_metrics,
        mean_train_sharpe=mean_train,
        pooled_oos_sharpe=pooled_sharpe,
        degradation_ratio=degradation,
        warnings=tuple(sorted(warnings)),
        notes=tuple(notes),
    )


def _drawdown(values: pd.Series) -> float:
    clean = values.dropna()
    if clean.empty:
        return 0.0
    equity = (1 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1
    return float(drawdown.min())
