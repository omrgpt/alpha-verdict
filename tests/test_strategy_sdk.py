"""Strategy authoring contract and causal feature tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alphaverdict import ResearchSnapshot, StockStrategy
from alphaverdict.data.technicals import (
    close_matrix,
    combine_ranks,
    cross_sectional_rank,
    ema,
    momentum,
    open_matrix,
    returns,
    rsi,
    sma,
    volatility,
    winsorize,
)
from alphaverdict.exceptions import ConfigurationError, StrategyContractError
from alphaverdict.strategy.loader import load_strategy
from alphaverdict.strategy.signals import SignalSet


@dataclass
class MappingStrategy(StockStrategy):
    name = "mapping"
    minimum_history = 2
    scale: float = 1.0

    def score(self, snapshot: ResearchSnapshot) -> dict[str, float]:
        return {symbol: index * self.scale for index, symbol in enumerate(snapshot.universe)}


def test_snapshot_exposes_only_known_evidence(demo_bundle) -> None:
    cutoff = demo_bundle.prices["timestamp"].drop_duplicates().iloc[100]
    snapshot = ResearchSnapshot.from_bundle(demo_bundle, cutoff)
    assert snapshot.as_of == cutoff
    assert snapshot.prices["timestamp"].max() <= cutoff
    assert len(snapshot.price_history(sessions=5)["timestamp"].unique()) == 5
    assert not snapshot.latest_prices().empty
    features = snapshot.latest_features(["quality_score"])
    assert features.columns.tolist() == ["quality_score"]
    assert not snapshot.feature_history("aurora", "quality_score").empty
    assert snapshot.known_events(include_future=False)["event_at"].max() <= cutoff
    with pytest.raises(ValueError, match="positive"):
        snapshot.price_history(sessions=0)


def test_signal_normalization_accepts_supported_outputs() -> None:
    date = pd.Timestamp("2024-01-01", tz="UTC")
    series = pd.Series({"bbb": 1.0, "aaa": 2.0}, name="x")
    signals = SignalSet.from_output(date, series)
    assert signals.frame["symbol"].tolist() == ["AAA", "BBB"]
    assert signals.top(1).iloc[0]["symbol"] == "AAA"
    assert len(SignalSet.from_output(date, {"AAA": 1.0}).eligible()) == 1
    frame = pd.DataFrame({"symbol": ["AAA"], "score": [1], "eligible": [False]})
    assert SignalSet.from_output(date, frame).top(1).empty
    assert SignalSet.from_output(date, signals) is signals


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (pd.DataFrame({"symbol": ["AAA"]}), "missing columns"),
        (pd.DataFrame({"symbol": ["AAA", "AAA"], "score": [1, 2]}), "duplicate"),
        (pd.DataFrame({"symbol": [""], "score": [1]}), "empty symbol"),
        (pd.DataFrame({"symbol": ["AAA"], "score": [np.nan]}), "finite"),
    ],
)
def test_signal_contract_rejects_malformed_frames(frame: pd.DataFrame, message: str) -> None:
    with pytest.raises(StrategyContractError, match=message):
        SignalSet(pd.Timestamp("2024-01-01"), frame)
    with pytest.raises(ValueError, match="positive"):
        SignalSet(pd.Timestamp("2024-01-01"), pd.DataFrame({"symbol": [], "score": []})).top(0)


def test_signal_contract_rejects_bad_types_and_dates() -> None:
    date = pd.Timestamp("2024-01-01", tz="UTC")
    with pytest.raises(StrategyContractError, match="must return"):
        SignalSet.from_output(date, [1, 2])
    wrong = SignalSet(
        pd.Timestamp("2024-01-02", tz="UTC"), pd.DataFrame({"symbol": ["A"], "score": [1]})
    )
    with pytest.raises(StrategyContractError, match="wrong timestamp"):
        SignalSet.from_output(date, wrong)


def test_strategy_enforces_universe_history_and_fingerprint(tiny_bundle) -> None:
    strategy = MappingStrategy(scale=2)
    snapshot = ResearchSnapshot.from_bundle(tiny_bundle, tiny_bundle.end)
    signals = strategy.screen(snapshot)
    assert signals.frame["eligible"].all()
    assert strategy.clone() is not strategy
    assert strategy.parameters() == {"scale": 2}
    assert len(strategy.fingerprint()) == 64


def test_technical_features_are_trailing_and_missing_safe(tiny_bundle) -> None:
    prices = tiny_bundle.prices
    closes = close_matrix(prices)
    opens = open_matrix(prices)
    assert closes.shape == opens.shape == (6, 2)
    assert returns(prices, 1).iloc[0].isna().all()
    assert sma(prices, 3).iloc[:2].isna().all().all()
    assert ema(prices, 3).shape == closes.shape
    assert momentum(prices, 3)["AAA"] == pytest.approx(105 / 102 - 1)
    assert momentum(prices.iloc[:2], 3).empty
    assert volatility(prices, window=3).notna().all()
    assert rsi(prices, period=2).shape[0] == 2


def test_cross_sectional_helpers() -> None:
    values = pd.Series({"A": 1.0, "B": 2.0, "C": np.nan})
    ranks = cross_sectional_rank(values)
    assert ranks["A"] == 0.5 and ranks["B"] == 1.0
    assert cross_sectional_rank(pd.Series(dtype=float)).empty
    assert cross_sectional_rank(pd.Series({"A": 1.0}))["A"] == 0.5
    clipped = winsorize(pd.Series(range(100)), (0.1, 0.9))
    assert clipped.min() == pytest.approx(9.9)
    with pytest.raises(ValueError, match="limits"):
        winsorize(values, (0.9, 0.1))
    combined = combine_ranks([(ranks, 0.75), (pd.Series({"A": 0.2}), 0.25)])
    assert combined["A"] == pytest.approx(0.425)
    assert combine_ranks([]).empty
    with pytest.raises(ValueError, match="non-negative"):
        combine_ranks([(values, -1)])


def test_strategy_loader_handles_local_and_installed_objects(tmp_path: Path) -> None:
    source = tmp_path / "strategy.py"
    source.write_text(
        "from alphaverdict.demo import DemoEvidenceStrategy\nStrategy = DemoEvidenceStrategy\n",
        encoding="utf-8",
    )
    loaded = load_strategy("strategy.py:Strategy", root=tmp_path)
    assert loaded.name == "synthetic-evidence-composite"
    installed = load_strategy("alphaverdict.demo:DemoEvidenceStrategy", root=tmp_path)
    assert installed.name == loaded.name
    with pytest.raises(ConfigurationError, match="must use"):
        load_strategy("invalid", root=tmp_path)
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_strategy("missing.py:Strategy", root=tmp_path)
    with pytest.raises(ConfigurationError, match="not found"):
        load_strategy("strategy.py:Missing", root=tmp_path)
    with pytest.raises(ConfigurationError, match="must inherit"):
        load_strategy("alphaverdict.demo:DEMO_SYMBOLS", root=tmp_path)
