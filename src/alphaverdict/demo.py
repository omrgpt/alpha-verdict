"""Deterministic demos used to prove the pipeline, never a market edge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphaverdict.agents.council import AuditCouncil
from alphaverdict.audit.models import AuditConfig, AuditReport
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataRequest
from alphaverdict.data.reference import RealMomentumStrategy, YFinanceBundleAdapter
from alphaverdict.data.technicals import momentum
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig, BacktestResult, RebalanceFrequency
from alphaverdict.report.render import RunArtifacts, write_run_report
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot

DEMO_SYMBOLS = ("AURORA", "BOREAL", "CIRRUS", "DELTA", "EMBER", "FJORD")


def synthetic_bundle(seed: int = 7, sessions: int = 520) -> DataBundle:
    """Build a reproducible multimodal fixture with no real securities or claims."""
    if sessions < 100:
        raise ValueError("synthetic demo requires at least 100 sessions")
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=sessions, tz="UTC")
    price_rows: list[dict[str, object]] = []
    feature_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    universe_rows: list[dict[str, object]] = []
    all_symbols = (*DEMO_SYMBOLS, "DEMO-BENCH")
    market_noise = rng.normal(0.00025, 0.009, sessions)
    for position, symbol in enumerate(all_symbols):
        idiosyncratic = rng.normal(0, 0.006 + position * 0.0003, sessions)
        drift = (position - 2) * 0.00005 if symbol != "DEMO-BENCH" else 0.0002
        returns = np.clip(market_noise + idiosyncratic + drift, -0.15, 0.15)
        closes = (70 + position * 8) * np.exp(np.cumsum(returns))
        overnight = rng.normal(0, 0.002, sessions)
        opens = closes * np.exp(overnight)
        intraday = np.abs(rng.normal(0.006, 0.002, sessions))
        highs = np.maximum(opens, closes) * (1 + intraday)
        lows = np.minimum(opens, closes) * (1 - intraday)
        volume = rng.integers(100_000, 2_000_000, sessions)
        for date, open_, high, low, close, amount in zip(
            dates, opens, highs, lows, closes, volume, strict=True
        ):
            price_rows.append(
                {
                    "symbol": symbol,
                    "timestamp": date,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": amount,
                    "source": "alphaverdict-synthetic-demo",
                }
            )
        universe_rows.append(
            {
                "symbol": symbol,
                "effective_from": dates[0],
                "effective_to": pd.NaT,
                "available_at": dates[0],
                "source": "alphaverdict-synthetic-demo",
            }
        )
        if symbol == "DEMO-BENCH":
            continue
        for quarter in range(70, sessions, 63):
            observed_at = dates[max(0, quarter - 20)]
            available_at = dates[quarter]
            quality = float(np.clip(0.35 + position * 0.08 + rng.normal(0, 0.05), 0, 1))
            feature_rows.append(
                {
                    "symbol": symbol,
                    "observed_at": observed_at,
                    "available_at": available_at,
                    "feature": "quality_score",
                    "value": quality,
                    "source": "alphaverdict-synthetic-demo",
                    "revision": 0,
                }
            )
        for event_index in range(90 + position * 3, sessions, 71):
            event_rows.append(
                {
                    "symbol": symbol,
                    "event_at": dates[event_index],
                    "available_at": dates[event_index],
                    "event_type": "news_sentiment",
                    "payload": {"sentiment": float(rng.uniform(-1, 1))},
                    "source": "alphaverdict-synthetic-demo",
                }
            )
    return DataBundle(
        prices=pd.DataFrame(price_rows),
        features=pd.DataFrame(feature_rows),
        events=pd.DataFrame(event_rows),
        universe=pd.DataFrame(universe_rows),
        metadata={
            "data_classification": "synthetic",
            "price_adjustment": "synthetic_total_return_like",
            "survivorship": "point_in_time",
            "purpose": "pipeline demonstration only",
        },
    )


@dataclass
class DemoEvidenceStrategy(StockStrategy):
    """Example only: combine price, fundamental-like, and event evidence."""

    name = "synthetic-evidence-composite"
    description = "Educational multimodal scoring contract; not a proposed strategy."
    minimum_history = 80
    momentum_sessions: int = 63

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        prices = snapshot.price_history(sessions=self.momentum_sessions + 1)
        price_score = momentum(prices, self.momentum_sessions)
        quality = snapshot.latest_features(["quality_score"]).get(
            "quality_score", pd.Series(dtype=float)
        )
        recent = snapshot.known_events(event_type="news_sentiment")
        cutoff = snapshot.as_of - pd.Timedelta(days=45)
        recent = recent[recent["event_at"] >= cutoff]
        if recent.empty:
            sentiment = pd.Series(dtype=float)
        else:
            sentiment = recent.groupby("symbol")["payload"].apply(
                lambda values: float(np.mean([float(item.get("sentiment", 0)) for item in values]))
            )
        symbols = [symbol for symbol in snapshot.universe if symbol != "DEMO-BENCH"]
        frame = pd.DataFrame(index=pd.Index(symbols, name="symbol"))
        frame["price"] = price_score.reindex(frame.index)
        frame["quality"] = pd.to_numeric(quality.reindex(frame.index), errors="coerce")
        frame["sentiment"] = sentiment.reindex(frame.index).fillna(0.0)
        frame["score"] = (
            frame["price"].rank(pct=True) * 0.50
            + frame["quality"].rank(pct=True) * 0.35
            + frame["sentiment"].rank(pct=True) * 0.15
        )
        frame["eligible"] = frame[["price", "quality"]].notna().all(axis=1)
        frame["rationale"] = "synthetic momentum + quality + news example"
        return frame.reset_index()[["symbol", "score", "eligible", "rationale"]]


@dataclass(frozen=True)
class DemoOutcome:
    """Complete result of one demo invocation, ready for rendering or testing."""

    result: BacktestResult
    audit: AuditReport
    artifacts: RunArtifacts


def _run_and_audit(
    bundle: DataBundle,
    strategy: StockStrategy,
    config: BacktestConfig,
    audit_config: AuditConfig | None,
    output: Path,
) -> DemoOutcome:
    engine = BacktestEngine(config)
    result = engine.run(bundle, strategy)
    audit = AuditCouncil().review(bundle, strategy, engine, result, audit_config)
    artifacts = write_run_report(result, audit, output)
    return DemoOutcome(result=result, audit=audit, artifacts=artifacts)


def run_synthetic_demo(
    output: Path = Path("demo-runs"),
    seed: int = 7,
    *,
    sessions: int = 520,
    fast_audit: bool = False,
) -> DemoOutcome:
    """Exercise every layer with clearly labelled synthetic data."""
    bundle = synthetic_bundle(seed=seed, sessions=sessions)
    strategy = DemoEvidenceStrategy(momentum_sessions=63 if sessions > 200 else 30)
    config = BacktestConfig(
        rebalance=RebalanceFrequency.WEEKLY,
        top_k=3,
        max_weight=0.40,
        benchmark_symbol="DEMO-BENCH",
        seed=seed,
    )
    audit_config = (
        AuditConfig(
            bootstrap_simulations=100,
            permutation_simulations=100,
            cost_multipliers=(0.0, 1.0, 2.0),
            causality_cutoffs=2,
            stability_folds=2,
            seed=seed,
        )
        if fast_audit
        else AuditConfig(bootstrap_simulations=200, permutation_simulations=200, seed=seed)
    )
    return _run_and_audit(bundle, strategy, config, audit_config, output)


def run_real_demo(
    output: Path = Path("demo-runs"),
    *,
    symbols: tuple[str, ...] | list[str] | None = None,
    benchmark: str = "SPY",
    period: str = "5y",
    top_k: int = 5,
    max_weight: float = 0.20,
    commission_bps: float = 5.0,
    slippage_bps: float = 10.0,
    seed: int = 7,
    fast_audit: bool = False,
) -> DemoOutcome:
    """Run the reference momentum contract on public market data via yfinance."""
    options: dict[str, Any] = {"benchmark": benchmark, "period": period}
    if symbols is not None:
        options["symbols"] = tuple(symbols)
    adapter = YFinanceBundleAdapter(**options)
    bundle = adapter.load(DataRequest())
    strategy = RealMomentumStrategy(benchmark_symbol=adapter.benchmark)
    config = BacktestConfig(
        rebalance=RebalanceFrequency.WEEKLY,
        top_k=top_k,
        max_weight=max_weight,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        benchmark_symbol=adapter.benchmark,
        seed=seed,
    )
    audit_config = (
        AuditConfig(
            bootstrap_simulations=100,
            permutation_simulations=100,
            causality_cutoffs=2,
            stability_folds=2,
            seed=seed,
        )
        if fast_audit
        else AuditConfig(seed=seed)
    )
    outcome = _run_and_audit(bundle, strategy, config, audit_config, output)
    return outcome
