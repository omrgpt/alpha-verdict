"""Configuration and result models for the deterministic engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

import pandas as pd


class RebalanceFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Weighting(StrEnum):
    EQUAL = "equal"
    RANK = "rank"
    SCORE = "score"


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Conservative daily-stock portfolio research assumptions."""

    start: str | pd.Timestamp | None = None
    end: str | pd.Timestamp | None = None
    rebalance: RebalanceFrequency = RebalanceFrequency.WEEKLY
    top_k: int = 10
    minimum_score: float | None = None
    weighting: Weighting = Weighting.EQUAL
    max_weight: float = 0.20
    commission_bps: float = 5.0
    slippage_bps: float = 10.0
    benchmark_symbol: str | None = None
    initial_capital: float = 100_000.0
    annual_risk_free_rate: float = 0.0
    seed: int = 7

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if not 0 < self.max_weight <= 1:
            raise ValueError("max_weight must be in (0, 1]")
        if self.commission_bps < 0 or self.slippage_bps < 0:
            raise ValueError("research costs cannot be negative")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.benchmark_symbol is not None:
            object.__setattr__(self, "benchmark_symbol", self.benchmark_symbol.strip().upper())
        object.__setattr__(self, "rebalance", RebalanceFrequency(self.rebalance))
        object.__setattr__(self, "weighting", Weighting(self.weighting))

    @property
    def periods_per_year(self) -> int:
        return {
            RebalanceFrequency.DAILY: 252,
            RebalanceFrequency.WEEKLY: 52,
            RebalanceFrequency.MONTHLY: 12,
        }[self.rebalance]

    @property
    def total_cost_bps(self) -> float:
        return self.commission_bps + self.slippage_bps


@dataclass(frozen=True)
class ScreenResult:
    as_of: pd.Timestamp
    ranked: pd.DataFrame
    strategy_name: str
    strategy_fingerprint: str
    data_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "strategy_name": self.strategy_name,
            "strategy_fingerprint": self.strategy_fingerprint,
            "data_fingerprint": self.data_fingerprint,
            "ranked": self.ranked.to_dict(orient="records"),
        }


@dataclass(frozen=True)
class BacktestResult:
    """Complete machine-readable research result; never an execution instruction."""

    config: BacktestConfig
    strategy_name: str
    strategy_fingerprint: str
    data_fingerprint: str
    returns: pd.DataFrame
    equity: pd.DataFrame
    holdings: pd.DataFrame
    signals: pd.DataFrame
    metrics: dict[str, float | int | None]
    benchmark_metrics: dict[str, float | int | None]
    warnings: tuple[str, ...] = ()
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
            output = frame.reset_index().to_dict(orient="records")
            for row in output:
                for key, value in tuple(row.items()):
                    if isinstance(value, pd.Timestamp):
                        row[key] = value.isoformat()
            return cast("list[dict[str, Any]]", output)

        return {
            "config": {
                "start": str(self.config.start) if self.config.start is not None else None,
                "end": str(self.config.end) if self.config.end is not None else None,
                "rebalance": self.config.rebalance.value,
                "top_k": self.config.top_k,
                "minimum_score": self.config.minimum_score,
                "weighting": self.config.weighting.value,
                "max_weight": self.config.max_weight,
                "commission_bps": self.config.commission_bps,
                "slippage_bps": self.config.slippage_bps,
                "benchmark_symbol": self.config.benchmark_symbol,
                "initial_capital": self.config.initial_capital,
                "annual_risk_free_rate": self.config.annual_risk_free_rate,
                "seed": self.config.seed,
            },
            "strategy": {
                "name": self.strategy_name,
                "fingerprint": self.strategy_fingerprint,
            },
            "data_fingerprint": self.data_fingerprint,
            "metrics": self.metrics,
            "benchmark_metrics": self.benchmark_metrics,
            "warnings": list(self.warnings),
            "returns": records(self.returns),
            "equity": records(self.equity),
            "holdings": records(self.holdings),
            "signals": records(self.signals),
            "manifest": self.manifest,
        }
