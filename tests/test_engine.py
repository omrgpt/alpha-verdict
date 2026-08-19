"""Causal screening, scheduling, portfolio accounting, and metric tests."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from alphaverdict.data.bundle import DataBundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.costs import friction, portfolio_turnover
from alphaverdict.engine.metrics import calculate_metrics, max_drawdown
from alphaverdict.engine.models import BacktestConfig, RebalanceFrequency, Weighting
from alphaverdict.engine.schedule import decision_dates, next_session
from alphaverdict.engine.screen import screen
from alphaverdict.exceptions import InsufficientDataError
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot


class RisingStrategy(StockStrategy):
    name = "rising"
    minimum_history = 2

    def score(self, snapshot: ResearchSnapshot) -> pd.Series:
        latest = snapshot.latest_prices().set_index("symbol")["close"]
        return latest


def test_rebalance_schedule_and_next_session() -> None:
    sessions = pd.date_range("2024-01-01", periods=45, freq="B", tz="UTC")
    assert decision_dates(sessions, RebalanceFrequency.DAILY).equals(sessions)
    weekly = decision_dates(sessions, RebalanceFrequency.WEEKLY)
    monthly = decision_dates(sessions, RebalanceFrequency.MONTHLY)
    assert 8 <= len(weekly) <= 10
    assert len(monthly) == 3
    assert next_session(sessions, sessions[0]) == sessions[1]
    assert next_session(sessions, sessions[-1]) is None
    bounded = decision_dates(
        sessions,
        RebalanceFrequency.DAILY,
        start=sessions[5],
        end=sessions[10],
    )
    assert bounded[0] == sessions[5] and bounded[-1] == sessions[10]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_k": 0},
        {"max_weight": 0},
        {"max_weight": 1.1},
        {"commission_bps": -1},
        {"slippage_bps": -1},
        {"initial_capital": 0},
    ],
)
def test_backtest_config_rejects_unsafe_assumptions(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        BacktestConfig(**kwargs)


def test_config_normalizes_enums_and_benchmark() -> None:
    config = BacktestConfig(rebalance="daily", weighting="rank", benchmark_symbol=" spy ")
    assert config.rebalance is RebalanceFrequency.DAILY
    assert config.weighting is Weighting.RANK
    assert config.benchmark_symbol == "SPY"
    assert config.periods_per_year == 252 and config.total_cost_bps == 15


def test_turnover_and_friction_include_cash() -> None:
    assert portfolio_turnover({}, {"AAA": 0.5}) == pytest.approx(0.5)
    assert portfolio_turnover({"AAA": 0.5}, {"BBB": 0.5}) == pytest.approx(0.5)
    assert friction(0.5, 20) == pytest.approx(0.001)
    with pytest.raises(ValueError, match="non-negative"):
        friction(-1, 1)
    drifted = BacktestEngine._drifted_weights({"AAA": 0.5}, {"AAA": 0.10})
    assert drifted["AAA"] == pytest.approx(0.55 / 1.05)
    assert BacktestEngine._drifted_weights({"AAA": 1.0}, {"AAA": -1.0}) == {}


def test_metrics_are_finite_and_benchmark_aware() -> None:
    index = pd.date_range("2024-01-01", periods=6, freq="W", tz="UTC")
    values = pd.Series([0.02, -0.01, 0.03, -0.02, 0.01, 0.04], index=index)
    benchmark = pd.Series([0.01, -0.02, 0.02, -0.01, 0, 0.02], index=index)
    metrics = calculate_metrics(
        values,
        periods_per_year=52,
        benchmark=benchmark,
        turnover=pd.Series(0.4, index=index),
        exposure=pd.Series(0.8, index=index),
    )
    assert metrics["periods"] == 6
    assert metrics["total_return"] is not None
    assert metrics["beta"] is not None
    assert metrics["average_turnover"] == pytest.approx(0.4)
    assert metrics["average_gross_exposure"] == pytest.approx(0.8)
    assert max_drawdown(values) < 0
    assert calculate_metrics(pd.Series(dtype=float), periods_per_year=252) == {
        "periods": 0,
        "total_return": 0.0,
    }
    assert max_drawdown(pd.Series(dtype=float)) == 0
    flat = calculate_metrics(pd.Series([0.0]), periods_per_year=252)
    assert flat["sharpe_ratio"] is None


def test_screen_returns_ranked_reproducible_result(tiny_bundle: DataBundle) -> None:
    result = screen(tiny_bundle, RisingStrategy(), top_n=1)
    assert result.ranked.iloc[0]["symbol"] == "BBB"
    assert result.ranked.iloc[0]["rank"] == 1
    assert result.to_dict()["strategy_name"] == "rising"
    with pytest.raises(ValueError, match="positive"):
        screen(tiny_bundle, RisingStrategy(), top_n=0)
    with pytest.raises(InsufficientDataError):
        screen(DataBundle(), RisingStrategy())


def test_backtest_runs_open_to_open_and_is_deterministic(
    demo_bundle,
    demo_strategy,
    demo_engine,
) -> None:
    first = demo_engine.run(demo_bundle, demo_strategy)
    second = demo_engine.run(demo_bundle, demo_strategy.clone())
    pd.testing.assert_frame_equal(first.returns, second.returns)
    assert first.manifest == second.manifest
    assert first.returns.index.min() > first.returns["decision_at"].min()
    assert (first.returns["execution_at"] > first.returns["decision_at"]).all()
    assert first.metrics["periods"] == len(first.returns)
    assert first.equity.columns.tolist() == ["strategy", "benchmark"]
    payload = first.to_dict()
    assert payload["manifest"]["run_id"] == first.manifest["run_id"]
    assert payload["warnings"]


@pytest.mark.parametrize("weighting", list(Weighting))
def test_all_weighting_modes_produce_bounded_exposure(
    demo_bundle,
    demo_strategy,
    weighting: Weighting,
) -> None:
    engine = BacktestEngine(
        BacktestConfig(
            rebalance="monthly",
            top_k=3,
            max_weight=0.4,
            weighting=weighting,
            benchmark_symbol="DEMO-BENCH",
        )
    )
    result = engine.run(demo_bundle, demo_strategy)
    assert (result.holdings["weight"] <= 0.4 + 1e-12).all()
    assert (result.returns["gross_exposure"] <= 1.0 + 1e-12).all()


def test_cost_multiplier_and_error_boundaries(demo_bundle, demo_strategy, demo_engine) -> None:
    base = demo_engine.run(demo_bundle, demo_strategy)
    stressed = demo_engine.with_cost_multiplier(3).run(demo_bundle, demo_strategy)
    assert stressed.returns["cost"].sum() >= base.returns["cost"].sum()
    with pytest.raises(ValueError, match="non-negative"):
        demo_engine.with_cost_multiplier(-1)
    with pytest.raises(InsufficientDataError, match="requires"):
        demo_engine.run(DataBundle(), demo_strategy)
    short = demo_bundle.with_prices(
        demo_bundle.prices[
            demo_bundle.prices["timestamp"].isin(
                demo_bundle.prices["timestamp"].drop_duplicates().head(3)
            )
        ]
    )
    with pytest.raises(InsufficientDataError, match="rebalance"):
        BacktestEngine(replace(demo_engine.config, rebalance="monthly")).run(short, demo_strategy)


def test_invalid_or_missing_execution_price_stays_in_cash(demo_bundle, demo_strategy) -> None:
    prices = demo_bundle.prices.copy()
    sessions = pd.DatetimeIndex(prices["timestamp"].drop_duplicates().sort_values())
    decisions = decision_dates(sessions, RebalanceFrequency.WEEKLY)
    target_date = next_session(sessions, decisions[-4])
    prices = prices[~((prices["symbol"] == "AURORA") & (prices["timestamp"] == target_date))]
    bundle = demo_bundle.with_prices(prices)
    engine = BacktestEngine(BacktestConfig(rebalance="weekly", top_k=6, max_weight=0.2))
    result = engine.run(bundle, demo_strategy)
    assert any("lacked valid execution prices" in item for item in result.warnings)
