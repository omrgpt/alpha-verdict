"""Regression tests from the adversarial torture battery (2026-08)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from alphaverdict.agents.base import AuditContext
from alphaverdict.agents.builtin import CausalityAgent
from alphaverdict.agents.council import AuditCouncil
from alphaverdict.audit.models import AuditConfig
from alphaverdict.data.bundle import DataBundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig, RebalanceFrequency
from alphaverdict.exceptions import StrategyContractError
from alphaverdict.report.render import write_run_report
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot
from alphaverdict.strategy.signals import SignalSet

META = {
    "price_adjustment": "split_and_dividend_adjusted",
    "survivorship": "point_in_time",
}


def _prices(symbols: tuple[str, ...] = ("AAA", "BBB"), days: int = 60) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=days, tz="UTC")
    rows = []
    for offset, sym in enumerate(symbols):
        for i, stamp in enumerate(dates):
            price = 100.0 + 0.05 * i + offset
            rows.append(
                {
                    "symbol": sym,
                    "timestamp": stamp,
                    "open": price * 0.9995,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "close": price * 1.0005,
                    "volume": 1_000.0,
                    "source": "test",
                }
            )
    return pd.DataFrame(rows)


def test_signal_set_accepts_columnless_empty_frame() -> None:
    """A strategy returning pd.DataFrame([]) means 'nothing eligible yet'."""
    normalized = SignalSet(pd.Timestamp("2024-03-01", tz="UTC"), pd.DataFrame([]))
    assert normalized.frame.empty
    assert list(normalized.frame.columns) == ["symbol", "score", "eligible", "rationale"]


def test_signal_set_still_rejects_partial_columns() -> None:
    with pytest.raises(StrategyContractError):
        SignalSet(pd.Timestamp("2024-03-01", tz="UTC"), pd.DataFrame({"score": [1.0]}))


def test_engine_survives_early_empty_outputs() -> None:
    """Early decision periods legitimately produce no scores; engine must not crash."""

    class LateStarter(StockStrategy):
        name = "late-starter"
        description = "empty until warmup"
        minimum_history = 30

        def clone(self) -> LateStarter:
            return self

        def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
            rows = [
                {"symbol": sym, "score": 1.0, "eligible": True, "rationale": "warm"}
                for sym in snapshot.universe
                if len(snapshot.prices[snapshot.prices["symbol"] == sym]) >= self.minimum_history
            ]
            return pd.DataFrame(rows)

    bundle = DataBundle(prices=_prices(), metadata=META)
    engine = BacktestEngine(BacktestConfig(rebalance=RebalanceFrequency.WEEKLY, top_k=2))
    result = engine.run(bundle, LateStarter())
    assert not result.returns.empty


def test_report_escapes_hostile_strings(tmp_path: Path) -> None:
    """Data-derived strings must never reach HTML unescaped (autoescape is explicit)."""
    evil = "<script>alert(1)</script>"

    class Evil(StockStrategy):
        name = f"{evil}-strat"
        description = evil
        minimum_history = 5

        def clone(self) -> Evil:
            return Evil()

        def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"symbol": s, "score": 1.0, "eligible": True, "rationale": evil}
                    for s in snapshot.universe
                ]
            )

    bundle = DataBundle(prices=_prices(days=40), metadata={**META, "note": evil})
    engine = BacktestEngine(BacktestConfig(rebalance=RebalanceFrequency.WEEKLY, top_k=2))
    result = engine.run(bundle, Evil())
    audit = AuditCouncil().review(bundle, Evil(), engine, result)
    artifacts = write_run_report(result, audit, tmp_path)
    html = artifacts.report.read_text(encoding="utf-8")
    assert evil not in html
    assert "&lt;script&gt;" in html


def test_causality_agent_reports_warmup_stability() -> None:
    """The stale-warmup probe runs and reports honest strategies as stable."""
    class Momentum(StockStrategy):
        name = "warm-momentum"
        description = ""
        minimum_history = 10

        def clone(self) -> Momentum:
            return Momentum()

        def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
            rows = []
            for sym in snapshot.universe:
                hist = snapshot.prices[snapshot.prices["symbol"] == sym]
                closes = hist.sort_values("timestamp")["close"]
                if len(closes) >= self.minimum_history:
                    rows.append({"symbol": sym, "score": float(closes.iloc[-1]),
                                 "eligible": True, "rationale": ""})
            return pd.DataFrame(rows)

    bundle = DataBundle(prices=_prices(days=80), metadata=META)
    engine = BacktestEngine(BacktestConfig(rebalance=RebalanceFrequency.WEEKLY, top_k=2))
    result = engine.run(bundle, Momentum())
    config = AuditConfig(bootstrap_simulations=100, permutation_simulations=100,
                         causality_cutoffs=3, stability_folds=2, seed=11)
    context = AuditContext(bundle, Momentum(), engine, result, config)
    report = CausalityAgent().review(context)
    assert report.measurements["warm_stable"] is True
    codes = {finding.code for finding in report.findings}
    assert "STRATEGY_STATEFUL_WARMUP" not in codes
