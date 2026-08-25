"""Adversarial bias zoo: planted-trap cases the audit council must catch.

Each case pairs a deliberately broken dataset or strategy with the finding
code(s) that prove detection. ``alphaverdict selfcheck`` runs every case
against a real council on synthetic data and fails loudly if any trap slips
through — quality assurance for the auditor itself.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphaverdict.agents.base import AuditContext
from alphaverdict.agents.builtin import (
    CausalityAgent,
    DataIntegrityAgent,
    TrialsAgent,
)
from alphaverdict.audit.ledger import TrialLedger
from alphaverdict.audit.models import AuditConfig
from alphaverdict.data.bundle import DataBundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig, BacktestResult, RebalanceFrequency
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot


class _Base(StockStrategy):
    name = "zoo-base"
    description = "zoo fixture"
    minimum_history = 6

    def clone(self) -> _Base:
        return self.__class__()


def _prices(
    symbols: tuple[str, ...] = ("AAA", "BBB", "CCC"),
    days: int = 90,
    seed: int = 5,
    drift: float = 0.0008,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=days, tz="UTC")
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        path = 100 * np.cumprod(1 + rng.normal(drift, 0.015, days))
        for stamp, price in zip(dates, path, strict=True):
            rows.append(
                {
                    "symbol": sym,
                    "timestamp": stamp,
                    "open": price * 0.9997,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "close": price * 1.0003,
                    "volume": 10_000.0,
                    "source": "zoo",
                }
            )
    return pd.DataFrame(rows)


def _clean_metadata() -> dict[str, Any]:
    return {
        "price_adjustment": "split_and_dividend_adjusted",
        "survivorship": "point_in_time",
    }


def _bundle(frame: pd.DataFrame, metadata: dict[str, Any] | None = None) -> DataBundle:
    return DataBundle(prices=frame, metadata=metadata or _clean_metadata())


def _engine(**kw: Any) -> BacktestEngine:
    return BacktestEngine(BacktestConfig(rebalance=RebalanceFrequency.WEEKLY, top_k=2, **kw))


# --------------------------------------------------------------- strategies


class _Momentum(_Base):
    name = "zoo-momentum"

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        rows = []
        for sym in snapshot.universe:
            hist = snapshot.prices[snapshot.prices["symbol"] == sym]
            closes = hist.sort_values("timestamp")["close"]
            if len(closes) >= self.minimum_history:
                rows.append(
                    {
                        "symbol": sym,
                        "score": float(closes.iloc[-1] / closes.iloc[0] - 1),
                        "eligible": True,
                        "rationale": "trail return",
                    }
                )
        return pd.DataFrame(rows, columns=["symbol", "score", "eligible", "rationale"])


class _LookaheadMetadata(_Base):
    """Reads a full-sample statistic smuggled through bundle metadata.

    Realistic adapter-shaped leak: a loader precomputes ``full_sample_drift``
    over every session (future included) and attaches it to the bundle, where
    naive strategy code treats it as configuration.
    """

    name = "zoo-lookahead-metadata"

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        smuggled = float(snapshot.metadata.get("full_sample_drift", 0.0))
        rows = []
        for sym in snapshot.universe:
            hist = snapshot.prices[snapshot.prices["symbol"] == sym]
            closes = hist.sort_values("timestamp")["close"]
            if len(closes) >= self.minimum_history:
                implied = float(closes.iloc[-1]) * (1 + smuggled)
                rows.append(
                    {
                        "symbol": sym,
                        "score": -abs(float(closes.iloc[-1]) - implied),
                        "eligible": True,
                        "rationale": "distance to full-sample drift",
                    }
                )
        return pd.DataFrame(rows, columns=["symbol", "score", "eligible", "rationale"])


class _Nondeterministic(_Base):
    name = "zoo-random"

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        rng = np.random.default_rng()
        return pd.DataFrame(
            [
                {
                    "symbol": sym,
                    "score": float(rng.normal()),
                    "eligible": True,
                    "rationale": "noise",
                }
                for sym in snapshot.universe
            ],
            columns=["symbol", "score", "eligible", "rationale"],
        )


class _FrozenWarmup(_Base):
    """Freezes a 'global mean' on its very first screen and reuses it forever.

    Deterministic per call, prefix-invariant under future perturbation — yet it
    leaks: decisions late in the sample are ranked against a statistic that was
    computed once, early, and never updated.
    """

    name = "zoo-frozen-warmup"
    minimum_history = 6

    def clone(self) -> _FrozenWarmup:
        # Naive implementations return a blank instance; the lazy cache is NOT
        # carried over, which is precisely how stale-warmup bugs behave.
        return _FrozenWarmup()

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        if getattr(self, "_frozen_mean", None) is None:
            self._frozen_mean = float(snapshot.prices["close"].mean())
        rows = []
        for sym in snapshot.universe:
            hist = snapshot.prices[snapshot.prices["symbol"] == sym]
            closes = hist.sort_values("timestamp")["close"]
            if len(closes) >= self.minimum_history:
                rows.append(
                    {
                        "symbol": sym,
                        "score": -abs(float(closes.iloc[-1]) - self._frozen_mean),
                        "eligible": True,
                        "rationale": "frozen-mean distance",
                    }
                )
        return pd.DataFrame(rows, columns=["symbol", "score", "eligible", "rationale"])


class _Churner(_Base):
    """High-churn ranking whose gross edge dies under plausible friction."""

    name = "zoo-churner"
    minimum_history = 40

    def __init__(self) -> None:
        self._rng = np.random.default_rng(17)

    def clone(self) -> _Churner:
        duplicate = _Churner()
        duplicate._rng = self._rng
        return duplicate

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        rows = []
        for sym in snapshot.universe:
            hist = snapshot.prices[snapshot.prices["symbol"] == sym]
            closes = hist.sort_values("timestamp")["close"]
            if len(closes) >= self.minimum_history:
                base = float(closes.pct_change().tail(20).std()) + 1e-9
                rows.append(
                    {
                        "symbol": sym,
                        "score": base * (1 + float(self._rng.normal(0, 0.05))),
                        "eligible": True,
                        "rationale": "churn",
                    }
                )
        return pd.DataFrame(rows, columns=["symbol", "score", "eligible", "rationale"])


# ------------------------------------------------------------------- cases


def _council_context(
    bundle: DataBundle, strategy: StockStrategy, engine: BacktestEngine, **config_kw: Any
) -> AuditContext:
    result = engine.run(bundle, strategy)
    settings: dict[str, Any] = {
        "bootstrap_simulations": 100,
        "permutation_simulations": 100,
        "cost_multipliers": (1.0,),
        "stability_folds": 2,
        "causality_cutoffs": 4,
        "seed": 11,
    }
    settings.update(config_kw)
    return AuditContext(
        bundle=bundle,
        strategy=strategy,
        engine=engine,
        result=result,
        config=AuditConfig(**settings),
    )


def case_lookahead_metadata() -> tuple[bool, str]:
    frame = _prices(days=120)
    smuggled = {**_clean_metadata(), "full_sample_drift": float(frame["close"].mean() / 100 - 1)}
    bundle = _bundle(frame, metadata=smuggled)
    engine = _engine()
    context = _council_context(bundle, _LookaheadMetadata(), engine)
    report = CausalityAgent().review(context)
    ok = not report.measurements.get("prefix_stable", True)
    return ok, f"prefix_stable={report.measurements.get('prefix_stable')}"


def case_frozen_warmup_state() -> tuple[bool, str]:
    bundle = _bundle(_prices(days=120))
    engine = _engine()
    context = _council_context(bundle, _FrozenWarmup(), engine)
    report = CausalityAgent().review(context)
    ok = any(f.code == "STRATEGY_STATEFUL_WARMUP" for f in report.findings)
    return ok, f"warm_stable={report.measurements.get('warm_stable')}"


def case_nondeterministic_strategy() -> tuple[bool, str]:
    bundle = _bundle(_prices())
    engine = _engine()
    context = _council_context(bundle, _Nondeterministic(), engine, causality_cutoffs=3)
    report = CausalityAgent().review(context)
    ok = (not report.measurements.get("reproducible", True)) and any(
        f.code == "STRATEGY_NONDETERMINISTIC" for f in report.findings
    )
    return ok, f"reproducible={report.measurements.get('reproducible')}"


def case_impossible_prices() -> tuple[bool, str]:
    frame = _prices(days=60)
    frame.loc[frame.index[:2], "high"] = frame.loc[frame.index[:2], "low"]
    frame.loc[frame.index[3], "close"] = -5.0
    bundle = _bundle(frame)
    engine = _engine()
    context = _council_context(bundle, _Momentum(), engine, causality_cutoffs=2)
    report = DataIntegrityAgent().review(context)
    ok = any(f.code == "DATA_PRICE_INVARIANT" for f in report.findings)
    return ok, "flagged" if ok else "missed"


def case_temporal_leak_features() -> tuple[bool, str]:
    base = _bundle(_prices(days=60))
    features = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "feature": "eps",
                "value": 2.0,
                "observed_at": pd.Timestamp("2024-02-15", tz="UTC"),
                "available_at": pd.Timestamp("2024-02-01", tz="UTC"),
                "revision": 0,
                "source": "zoo",
            },
        ]
    )
    leaked = DataBundle(prices=base.prices, features=features, metadata=_clean_metadata())
    engine = _engine()
    context = _council_context(leaked, _Momentum(), engine, causality_cutoffs=2)
    report = DataIntegrityAgent().review(context)
    ok = any(f.code == "DATA_TEMPORAL_LEAK" for f in report.findings)
    return ok, "flagged" if ok else "missed"


def case_survivorship_undisclosed() -> tuple[bool, str]:
    bundle = _bundle(_prices(days=60), metadata={"price_adjustment": "split_and_dividend_adjusted"})
    engine = _engine()
    context = _council_context(bundle, _Momentum(), engine, causality_cutoffs=2)
    report = DataIntegrityAgent().review(context)
    ok = any(f.code == "DATA_SURVIVORSHIP_UNKNOWN" for f in report.findings)
    return ok, "flagged" if ok else "missed"


def case_cost_fragile_turnover() -> tuple[bool, str]:
    frame = _prices(symbols=("AAA", "BBB", "CCC", "DDD"), days=240, seed=23, drift=0.0009)
    bundle = _bundle(frame)
    engine = BacktestEngine(
        BacktestConfig(
            rebalance=RebalanceFrequency.DAILY, top_k=2, commission_bps=25.0, slippage_bps=50.0
        )
    )
    result = engine.run(bundle, _Churner())
    from alphaverdict.agents.council import AuditCouncil  # noqa: PLC0415 - avoids import cycle

    council = AuditCouncil(agents=())  # replaced below with the two relevant reviewers
    robustness = next(a for a in council_agents() if a.name == "robustness")
    performance = next(a for a in council_agents() if a.name == "performance")
    object.__setattr__(council, "agents", (robustness, performance))
    audit_config = AuditConfig(
        cost_multipliers=(0.0, 1.0, 2.0),
        bootstrap_simulations=100,
        permutation_simulations=100,
        stability_folds=4,
        seed=11,
    )
    audit = council.review(bundle, _Churner(), engine, result, audit_config)
    codes = {f.code for f in audit.findings}
    ok = bool(codes & {"COST_FRAGILE", "FOLD_INSTABILITY"})
    return ok, f"codes={sorted(codes)}"


def council_agents() -> tuple[Any, ...]:
    from alphaverdict.agents.builtin import (  # noqa: PLC0415 - avoids import cycle
        PerformanceAgent,
        RobustnessAgent,
    )

    return (RobustnessAgent(), PerformanceAgent())


def _run_small_backtest() -> BacktestResult:
    bundle = _bundle(_prices(days=70))
    return _engine().run(bundle, _Momentum())


def case_ledger_tampering() -> tuple[bool, str]:
    """Editing one ledger entry must break the hash chain."""
    with tempfile.TemporaryDirectory() as room:
        path = Path(room) / "trials.jsonl"
        ledger = TrialLedger(path)
        ledger.record_note("baseline hypothesis frozen")
        ledger.record_result(_run_small_backtest())
        lines = path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[0])
        tampered["label"] = "edited after the fact"
        lines[0] = json.dumps(tampered, sort_keys=True, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        bundle = _bundle(_prices(days=60))
        engine = _engine()
        context = _council_context(bundle, _Momentum(), engine, causality_cutoffs=2)
        report = TrialsAgent(ledger_path=str(path)).review(context)
        ok = any(f.code == "TRIALS_LEDGER_TAMPERED" for f in report.findings)
        return ok, "chain break detected" if ok else "tamper missed"


def case_underdeclared_trials() -> tuple[bool, str]:
    """Three recorded variants vs n_trials=1 must flag TRIALS_UNDERDECLARED."""
    with tempfile.TemporaryDirectory() as room:
        path = Path(room) / "trials.jsonl"
        ledger = TrialLedger(path)
        for lookback in ("fast", "mid", "slow"):
            stub = _run_small_backtest()
            object.__setattr__(stub, "strategy_fingerprint", f"fp-{lookback}")
            ledger.record_result(stub)
        bundle = _bundle(_prices(days=60))
        engine = _engine()
        context = _council_context(bundle, _Momentum(), engine, causality_cutoffs=2, n_trials=1)
        report = TrialsAgent(ledger_path=str(path)).review(context)
        ok = any(f.code == "TRIALS_UNDERDECLARED" for f in report.findings)
        return ok, f"variants={report.measurements.get('distinct_variants')}"


CASES: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
    ("lookahead-metadata-smuggling", case_lookahead_metadata),
    ("frozen-warmup-state", case_frozen_warmup_state),
    ("nondeterministic-strategy", case_nondeterministic_strategy),
    ("impossible-prices", case_impossible_prices),
    ("feature-temporal-leak", case_temporal_leak_features),
    ("survivorship-undisclosed", case_survivorship_undisclosed),
    ("cost-fragile-turnover", case_cost_fragile_turnover),
    ("ledger-tampering-detected", case_ledger_tampering),
    ("underdeclared-trials", case_underdeclared_trials),
]


def run_self_check(print_fn: Callable[[str], None] | None = None) -> list[str]:
    """Run every zoo case; return the names of any traps the council missed."""
    emit = print_fn or _silent
    failures: list[str] = []
    for name, case in CASES:
        try:
            caught, detail = case()
        except Exception as exc:  # noqa: BLE001 - a crashing case is a failed case
            caught, detail = False, f"{type(exc).__name__}: {exc}"
        status = "caught" if caught else "MISSED"
        emit(f"  [{status:>6}] {name} — {detail}")
        if not caught:
            failures.append(name)
    return failures


def _silent(_message: str) -> None:
    return None
