"""Tests for the public-data reference adapter and demo strategy."""

from __future__ import annotations

import sys
import types
from typing import Any

import numpy as np
import pandas as pd
import pytest

from alphaverdict.data import reference as reference_module
from alphaverdict.data.adapter import HealthStatus
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataRequest
from alphaverdict.data.reference import (
    DEFAULT_BENCHMARK,
    RealMomentumStrategy,
    YFinanceBundleAdapter,
)
from alphaverdict.exceptions import ConfigurationError, InsufficientDataError
from alphaverdict.strategy.context import ResearchSnapshot

SESSIONS = 300


def _frame_for(symbols: list[str], sessions: int = SESSIONS) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=sessions)
    fields = ["Open", "High", "Low", "Close", "Volume"]
    columns = pd.MultiIndex.from_product([symbols, fields])
    data: dict[tuple[str, str], list[float]] = {}
    for position, symbol in enumerate(symbols):
        base = 50.0 + 10.0 * position
        closes = base * np.exp(np.cumsum(np.full(sessions, 0.0004 * (position + 1))))
        opens = closes * 0.999
        highs = closes * 1.01
        lows = opens * 0.99
        volumes = np.linspace(1_000, 2_000, sessions)
        for name, values in zip(fields, [opens, highs, lows, closes, volumes], strict=True):
            data[(symbol, name)] = [round(float(value), 6) for value in values]
    return pd.DataFrame(data, index=dates, columns=columns)


@pytest.fixture()
def fake_yfinance(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Inject a deterministic stand-in for the optional yfinance dependency."""
    calls: dict[str, Any] = {}

    def download(**kwargs: Any) -> pd.DataFrame:
        calls.update(kwargs)
        tickers = [str(item).upper() for item in kwargs.get("tickers", [])]
        return _frame_for(tickers)

    module = types.ModuleType("yfinance")
    module.download = download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return calls


def test_health_passes_when_dependency_available(fake_yfinance: dict[str, Any]) -> None:
    adapter = YFinanceBundleAdapter()
    health = adapter.health()
    assert health.status is HealthStatus.PASS
    assert "reference symbols" in health.detail


def test_health_fails_without_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_missing() -> Any:
        raise ConfigurationError("install alphaverdict[real]")

    monkeypatch.setattr(reference_module, "_require_yfinance", raise_missing)
    adapter = YFinanceBundleAdapter()
    health = adapter.health()
    assert health.status is HealthStatus.FAIL
    assert "alphaverdict[real]" in health.detail


def test_load_builds_canonical_bundle(fake_yfinance: dict[str, Any]) -> None:
    adapter = YFinanceBundleAdapter(symbols=("aapl", "msft", "NVDA"), benchmark="SPY", period="2y")
    bundle = adapter.load(DataRequest())
    expected_symbols = {"AAPL", "MSFT", "NVDA", "SPY"}
    loaded = set(bundle.prices["symbol"].unique())
    assert loaded == expected_symbols
    assert set(bundle.symbols) == expected_symbols
    assert len(bundle.universe) == len(expected_symbols)
    assert bundle.metadata["adapter"] == "yfinance"
    assert bundle.metadata["data_classification"] == "public_market_data"
    assert bundle.metadata["price_adjustment"] == "split_and_dividend_adjusted"
    assert "snapshot" in bundle.metadata["survivorship"]
    assert fake_yfinance["period"] == "2y"
    assert fake_yfinance["auto_adjust"] is True
    first_session = bundle.prices["timestamp"].min()
    universe_rows = bundle.universe[bundle.universe["symbol"] == "AAPL"]
    assert universe_rows["effective_from"].iloc[0] == first_session


def test_load_respects_requested_symbols(fake_yfinance: dict[str, Any]) -> None:
    adapter = YFinanceBundleAdapter()
    bundle = adapter.load(DataRequest(symbols=("AAPL",)))
    assert set(bundle.prices["symbol"].unique()) == {"AAPL"}
    assert fake_yfinance["tickers"] == ["AAPL"]


def test_load_rejects_unknown_symbols(fake_yfinance: dict[str, Any]) -> None:
    adapter = YFinanceBundleAdapter()
    with pytest.raises(InsufficientDataError, match="intersect"):
        adapter.load(DataRequest(symbols=("ZZZZ",)))


def test_load_rejects_empty_download(
    monkeypatch: pytest.MonkeyPatch, fake_yfinance: dict[str, Any]
) -> None:
    def download(**kwargs: Any) -> pd.DataFrame:
        return pd.DataFrame()

    sys.modules["yfinance"].download = download  # type: ignore[attr-defined]
    adapter = YFinanceBundleAdapter(symbols=("AAPL",))
    with pytest.raises(InsufficientDataError, match="no usable daily"):
        adapter.load(DataRequest())


def test_download_failure_is_wrapped(fake_yfinance: dict[str, Any]) -> None:
    def download(**kwargs: Any) -> pd.DataFrame:
        raise ConnectionError("remote reset")

    sys.modules["yfinance"].download = download  # type: ignore[attr-defined]
    adapter = YFinanceBundleAdapter(symbols=("AAPL",))
    with pytest.raises(InsufficientDataError, match="download failed"):
        adapter.load(DataRequest())


def test_flat_single_symbol_frame(fake_yfinance: dict[str, Any]) -> None:
    single = _frame_for(["AAPL"])
    single.columns = ["Open", "High", "Low", "Close", "Volume"]

    def download(**kwargs: Any) -> pd.DataFrame:
        return single

    sys.modules["yfinance"].download = download  # type: ignore[attr-defined]
    adapter = YFinanceBundleAdapter(symbols=("AAPL",))
    bundle = adapter.load(DataRequest())
    assert set(bundle.prices["symbol"].unique()) == {"AAPL"}
    assert bundle.prices["close"].notna().all()


def test_rows_with_missing_ohlc_are_dropped(fake_yfinance: dict[str, Any]) -> None:
    frame = _frame_for(["AAPL"])
    frame.iloc[0, frame.columns.get_loc(("AAPL", "Close"))] = np.nan

    def download(**kwargs: Any) -> pd.DataFrame:
        return frame

    sys.modules["yfinance"].download = download  # type: ignore[attr-defined]
    adapter = YFinanceBundleAdapter(symbols=("AAPL",))
    bundle = adapter.load(DataRequest())
    assert bundle.prices[["open", "high", "low", "close"]].notna().all().all()


def test_duplicate_provider_sessions_are_last_wins(fake_yfinance: dict[str, Any]) -> None:
    frame = _frame_for(["AAPL"])
    duplicated = pd.concat([frame, frame.iloc[[-1]]])

    def download(**kwargs: Any) -> pd.DataFrame:
        return duplicated

    sys.modules["yfinance"].download = download  # type: ignore[attr-defined]
    adapter = YFinanceBundleAdapter(symbols=("AAPL",))
    bundle = adapter.load(DataRequest())
    assert not bundle.prices.duplicated(["symbol", "timestamp"]).any()


def test_adapter_requires_symbols() -> None:
    with pytest.raises(ConfigurationError, match="at least one symbol"):
        YFinanceBundleAdapter(symbols=())


def _momentum_bundle() -> Any:
    sessions = 260
    dates = pd.bdate_range("2023-01-02", periods=sessions, tz="UTC")
    rows: list[dict[str, object]] = []
    universe_symbols = ("AAA", "BBB", "CCC", "DDD")
    for position, symbol in enumerate(universe_symbols):
        drift = 0.0008 - position * 0.0004
        closes = 100.0 * np.exp(np.cumsum(np.full(sessions, drift)))
        for date, close in zip(dates, closes, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": date,
                    "open": close * 0.999,
                    "high": close * 1.005,
                    "low": close * 0.995,
                    "close": close,
                    "volume": 1_000.0,
                    "source": "fixture",
                }
            )
    for date, close in zip(dates, np.linspace(400, 420, sessions), strict=True):
        rows.append(
            {
                "symbol": DEFAULT_BENCHMARK,
                "timestamp": date,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1_000.0,
                "source": "fixture",
            }
        )
    universe = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "effective_from": dates[0],
                "effective_to": pd.NaT,
                "available_at": dates[0],
                "source": "fixture",
            }
            for symbol in (*universe_symbols, DEFAULT_BENCHMARK)
        ]
    )
    return DataBundle(prices=pd.DataFrame(rows), universe=universe)


def test_real_momentum_strategy_excludes_benchmark() -> None:
    bundle = _momentum_bundle()
    as_of = pd.Timestamp(bundle.prices["timestamp"].max())
    snapshot = ResearchSnapshot.from_bundle(bundle, as_of)
    strategy = RealMomentumStrategy(benchmark_symbol=DEFAULT_BENCHMARK)
    frame = strategy.score(snapshot)
    assert list(frame.columns) == ["symbol", "score", "eligible", "rationale"]
    assert "SPY" not in set(frame["symbol"])
    assert frame["score"].notna().all()
    assert frame["eligible"].all()

    signals = strategy.screen(snapshot)
    comparable_first = signals.comparable()
    comparable_second = strategy.screen(snapshot).comparable()
    pd.testing.assert_frame_equal(comparable_first, comparable_second)
    assert signals.eligible()["score"].is_monotonic_decreasing


def test_real_momentum_strategy_marks_short_history_ineligible() -> None:
    bundle = _momentum_bundle()
    early = pd.Timestamp(min(bundle.prices["timestamp"]) + pd.Timedelta(days=14))
    snapshot = ResearchSnapshot.from_bundle(bundle, early)
    strategy = RealMomentumStrategy(benchmark_symbol=DEFAULT_BENCHMARK)
    signals = strategy.screen(snapshot)
    if not signals.frame.empty:
        assert not signals.frame["eligible"].any()


def test_strategy_output_with_all_nan_scores_is_ineligible_only() -> None:
    bundle = _momentum_bundle()
    first_session = pd.Timestamp(min(bundle.prices["timestamp"]))
    snapshot = ResearchSnapshot.from_bundle(bundle, first_session)
    strategy = RealMomentumStrategy(benchmark_symbol=DEFAULT_BENCHMARK)
    frame = strategy.score(snapshot)
    # No crash on empty history: scores are NaN and nothing may be marked eligible.
    assert frame["eligible"].dtype == bool
    assert not frame["eligible"].any()
    signals = strategy.screen(snapshot)
    assert signals.eligible().empty
    assert signals.top(2).empty
