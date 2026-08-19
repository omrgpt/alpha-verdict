"""Shared deterministic fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from alphaverdict.data.bundle import DataBundle
from alphaverdict.demo import DemoEvidenceStrategy, synthetic_bundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig, BacktestResult, RebalanceFrequency


@pytest.fixture(scope="session")
def demo_bundle() -> DataBundle:
    return synthetic_bundle(seed=11, sessions=180)


@pytest.fixture(scope="session")
def demo_strategy() -> DemoEvidenceStrategy:
    return DemoEvidenceStrategy(momentum_sessions=30)


@pytest.fixture(scope="session")
def demo_engine() -> BacktestEngine:
    return BacktestEngine(
        BacktestConfig(
            rebalance=RebalanceFrequency.WEEKLY,
            top_k=3,
            max_weight=0.40,
            benchmark_symbol="DEMO-BENCH",
            seed=11,
        )
    )


@pytest.fixture(scope="session")
def demo_result(demo_bundle, demo_strategy, demo_engine) -> BacktestResult:
    return demo_engine.run(demo_bundle, demo_strategy)


@pytest.fixture()
def tiny_bundle() -> DataBundle:
    dates = pd.date_range("2024-01-01", periods=6, freq="B", tz="UTC")
    rows: list[dict[str, object]] = []
    for symbol, offset in (("AAA", 0.0), ("BBB", 10.0)):
        for index, date in enumerate(dates):
            close = 100 + offset + index
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": date,
                    "open": close - 0.5,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1_000 + index,
                    "source": "fixture",
                }
            )
    return DataBundle(prices=pd.DataFrame(rows), metadata={"fixture": True})
