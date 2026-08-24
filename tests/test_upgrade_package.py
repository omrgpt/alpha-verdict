"""Tests for the performance and research-validity upgrade package."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from alphaverdict.agents.base import AuditContext
from alphaverdict.agents.builtin import RobustnessAgent
from alphaverdict.audit.models import AuditConfig
from alphaverdict.cli import app
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataRequest
from alphaverdict.data.technicals import momentum
from alphaverdict.demo import DemoEvidenceStrategy, run_synthetic_demo, synthetic_bundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig, RebalanceFrequency
from alphaverdict.engine.walkforward import WalkForwardConfig, walk_forward
from alphaverdict.exceptions import InsufficientDataError
from alphaverdict.strategy.context import ResearchSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bundle_780() -> DataBundle:
    return synthetic_bundle(seed=13, sessions=620)


@pytest.fixture(scope="module")
def engine_weekly() -> BacktestEngine:
    return BacktestEngine(
        BacktestConfig(
            rebalance=RebalanceFrequency.WEEKLY,
            top_k=3,
            max_weight=0.40,
            benchmark_symbol="DEMO-BENCH",
            seed=13,
        )
    )


def _strategy() -> DemoEvidenceStrategy:
    return DemoEvidenceStrategy(momentum_sessions=63)


# ---------------------------------------------------------------------------
# Upgrade 1: prepare/replay split


class TestPrepareReplay:
    def test_replay_matches_run_at_base_costs(
        self, bundle_780: DataBundle, engine_weekly: BacktestEngine
    ) -> None:
        strategy = _strategy()
        direct = engine_weekly.run(bundle_780, strategy.clone())
        plan = engine_weekly.prepare(bundle_780, strategy.clone())
        replayed = engine_weekly.replay(plan)
        pd.testing.assert_frame_equal(direct.returns, replayed.returns)
        assert direct.manifest["run_id"] == replayed.manifest["run_id"]
        assert direct.metrics["total_return"] == pytest.approx(replayed.metrics["total_return"])

    def test_replay_with_higher_costs_reduces_returns(
        self, bundle_780: DataBundle, engine_weekly: BacktestEngine
    ) -> None:
        plan = engine_weekly.prepare(bundle_780, _strategy())
        low = engine_weekly.replay(plan, commission_bps=0.0, slippage_bps=0.0)
        high = engine_weekly.replay(plan, commission_bps=50.0, slippage_bps=50.0)
        low_total = float(low.metrics["total_return"] or 0.0)
        high_total = float(high.metrics["total_return"] or 0.0)
        assert high_total <= low_total
        assert set(low.returns.columns) == set(high.returns.columns)

    def test_plan_is_strategy_cost_independent(
        self, bundle_780: DataBundle, engine_weekly: BacktestEngine
    ) -> None:
        plan = engine_weekly.prepare(bundle_780, _strategy())
        assert plan.periods
        first = plan.periods[0]
        assert {"decision_at", "execution_at", "weights", "gross_return"} <= set(first)

    def test_robustness_agent_uses_replay_path(
        self, bundle_780: DataBundle, engine_weekly: BacktestEngine
    ) -> None:

        strategy = _strategy()
        result = engine_weekly.run(bundle_780, strategy)
        context = AuditContext(
            bundle_780,
            strategy,
            engine_weekly,
            result,
            AuditConfig(seed=13),
        )
        report = RobustnessAgent().review(context)
        curve = report.measurements["cost_curve"]
        assert curve
        assert "1x" in curve


# ---------------------------------------------------------------------------
# Upgrade 2: snapshot cached matrices


class TestSnapshotCache:
    def test_trailing_momentum_matches_technicals(self, bundle_780: DataBundle) -> None:

        as_of = pd.Timestamp(bundle_780.prices["timestamp"].max())
        snapshot = ResearchSnapshot.from_bundle(bundle_780, as_of)
        prices = snapshot.price_history(sessions=64)
        expected = momentum(prices, 63)
        actual = snapshot.trailing_momentum(63)
        pd.testing.assert_series_equal(actual.dropna(), expected.dropna())

    def test_close_matrix_cached_identity(self, bundle_780: DataBundle) -> None:
        as_of = pd.Timestamp(bundle_780.prices["timestamp"].max())
        snapshot = ResearchSnapshot.from_bundle(bundle_780, as_of)
        assert snapshot.close_matrix() is snapshot.close_matrix()
        assert snapshot.open_matrix() is snapshot.open_matrix()

    def test_matrices_reflect_snapshot_boundary(self, bundle_780: DataBundle) -> None:
        timestamps = sorted(set(bundle_780.prices["timestamp"]))
        early = ResearchSnapshot.from_bundle(bundle_780, pd.Timestamp(timestamps[100]))
        late = ResearchSnapshot.from_bundle(bundle_780, pd.Timestamp(timestamps[-1]))
        assert len(early.close_matrix()) < len(late.close_matrix())

    def test_invalid_lookback_raises(self, bundle_780: DataBundle) -> None:
        as_of = pd.Timestamp(bundle_780.prices["timestamp"].max())
        snapshot = ResearchSnapshot.from_bundle(bundle_780, as_of)
        with pytest.raises(ValueError, match="lookback"):
            snapshot.trailing_momentum(0)


# ---------------------------------------------------------------------------
# Upgrade 3: adapter batching, retry, cache


class _FakeModule:
    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.fail_times = fail_times

    def download(self, **kwargs: Any) -> pd.DataFrame:
        tickers = [str(item).upper() for item in kwargs.get("tickers", [])]
        self.calls.append(tickers)
        if len(self.calls) <= self.fail_times:
            raise ConnectionError("transient failure")
        dates = pd.bdate_range("2024-01-01", periods=60)
        fields = ["Open", "High", "Low", "Close", "Volume"]
        columns = pd.MultiIndex.from_product([tickers, fields])
        frame = pd.DataFrame(
            np.linspace(10.0, 20.0, len(dates) * len(columns)).reshape(len(dates), -1),
            index=dates,
            columns=columns,
        )
        return frame


@pytest.fixture()
def fake_module(monkeypatch: pytest.MonkeyPatch) -> _FakeModule:
    module = _FakeModule()
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return module


def _adapter(**kwargs: Any) -> Any:
    from alphaverdict.data.reference import YFinanceBundleAdapter  # noqa: PLC0415 - optional extra

    defaults: dict[str, Any] = {"symbols": ("AAPL", "MSFT", "NVDA", "XOM", "CVX")}
    defaults.update(kwargs)
    return YFinanceBundleAdapter(**defaults)


def test_download_chunked_into_batches(fake_module: _FakeModule) -> None:
    symbols = tuple(f"S{i:02d}" for i in range(30))
    module = _FakeModule()
    sys.modules["yfinance"] = module
    adapter = _adapter(symbols=symbols)
    bundle = adapter.load(DataRequest())
    assert not bundle.prices.empty
    assert all(len(batch) <= 25 for batch in module.calls)
    assert sum(len(batch) for batch in module.calls) >= 30


def test_retry_recovers_from_transient_failures(fake_module: _FakeModule) -> None:
    module = _FakeModule(fail_times=2)
    sys.modules["yfinance"] = module
    adapter = _adapter(symbols=("AAPL",))
    bundle = adapter.load(DataRequest())
    assert not bundle.prices.empty
    assert len(module.calls) == 3


def test_permanent_failure_raises_after_attempts(fake_module: _FakeModule) -> None:
    class AlwaysFails(_FakeModule):
        def download(self, **kwargs: Any) -> pd.DataFrame:
            self.calls.append([])
            raise ConnectionError("down")

    module = AlwaysFails()
    sys.modules["yfinance"] = module
    adapter = _adapter(symbols=("AAPL",))
    with pytest.raises(InsufficientDataError, match="download failed"):
        adapter.load(DataRequest())


def test_disk_cache_roundtrip(tmp_path: Path, fake_module: _FakeModule) -> None:
    module = _FakeModule()
    sys.modules["yfinance"] = module
    cache_dir = tmp_path / "cache"
    adapter = _adapter(symbols=("AAPL",), cache_dir=cache_dir)
    first = adapter.load(DataRequest())
    second = adapter.load(DataRequest())
    assert first.fingerprint() == second.fingerprint()
    files = list(cache_dir.glob("yfinance-*.pkl"))
    assert len(files) == 1


def test_stale_cache_refetches(tmp_path: Path, fake_module: _FakeModule) -> None:
    module = _FakeModule()
    sys.modules["yfinance"] = module
    cache_dir = tmp_path / "cache"
    adapter = _adapter(symbols=("AAPL",), cache_dir=cache_dir, max_age_hours=0.0)
    adapter.load(DataRequest())
    path = next(cache_dir.glob("*.pkl"))
    stale = time.time() - 7200

    os.utime(path, (stale, stale))
    calls_before = len(module.calls)
    adapter.load(DataRequest())
    assert len(module.calls) > calls_before


def test_corrupted_cache_falls_back_to_download(tmp_path: Path, fake_module: _FakeModule) -> None:
    module = _FakeModule()
    sys.modules["yfinance"] = module
    cache_dir = tmp_path / "cache"
    adapter = _adapter(symbols=("AAPL",), cache_dir=cache_dir)
    adapter.load(DataRequest())
    path = next(cache_dir.glob("*.pkl"))
    path.write_bytes(b"not a pickle")
    bundle = adapter.load(DataRequest())
    assert not bundle.prices.empty


# ---------------------------------------------------------------------------
# Upgrade 9: walk-forward engine


@dataclass
class PriceOnlyMomentum(DemoEvidenceStrategy):
    """Price-only variant so walk-forward fixtures need no feature tables."""

    name = "price-only-momentum"
    minimum_history = 30

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        scores = snapshot.trailing_momentum(self.momentum_sessions)
        symbols = [s for s in snapshot.universe if s != "DEMO-BENCH"]
        frame = pd.DataFrame(index=pd.Index(sorted(set(symbols)), name="symbol"))
        frame["score"] = pd.to_numeric(scores.reindex(frame.index), errors="coerce")
        frame["eligible"] = frame["score"].notna()
        frame["rationale"] = "fixture momentum"
        return frame.reset_index()[["symbol", "score", "eligible", "rationale"]]


def _wf_bundle(trend_sessions: int = 900) -> DataBundle:
    rng = np.random.default_rng(23)
    dates = pd.bdate_range("2022-01-03", periods=trend_sessions, tz="UTC")
    rows: list[dict[str, object]] = []
    market_noise = rng.normal(0.0003, 0.008, trend_sessions)
    universe = ("AAA", "BBB", "CCC", "DDD")
    for position, symbol in enumerate(universe):
        drift = 0.0009 - position * 0.00035
        returns = np.clip(market_noise + rng.normal(0, 0.004, trend_sessions) + drift, -0.12, 0.12)
        closes = 60.0 * np.exp(np.cumsum(returns))
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
    for date, close in zip(dates, np.linspace(200, 260, trend_sessions), strict=True):
        rows.append(
            {
                "symbol": "DEMO-BENCH",
                "timestamp": date,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1_000.0,
                "source": "fixture",
            }
        )
    universe_rows = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "effective_from": dates[0],
                "effective_to": pd.NaT,
                "available_at": dates[0],
                "source": "fixture",
            }
            for symbol in (*universe, "DEMO-BENCH")
        ]
    )
    metadata = {"survivorship": "point_in_time", "price_adjustment": "none"}
    return DataBundle(prices=pd.DataFrame(rows), universe=universe_rows, metadata=metadata)


class TestWalkForward:
    @pytest.fixture(scope="class")
    def result(self) -> Any:
        bundle = _wf_bundle()
        engine = BacktestEngine(
            BacktestConfig(
                rebalance=RebalanceFrequency.WEEKLY,
                top_k=2,
                max_weight=0.55,
                benchmark_symbol="DEMO-BENCH",
                seed=23,
            )
        )
        settings = WalkForwardConfig(train_periods=40, test_periods=12, embargo_periods=2)
        return walk_forward(bundle, PriceOnlyMomentum(momentum_sessions=21), engine, settings)

    def test_produces_multiple_contiguous_folds(self, result: Any) -> None:
        assert len(result.folds) >= 2
        for earlier, later in zip(result.folds, list(result.folds)[1:], strict=False):
            assert earlier.test_start < later.test_start
            assert later.train_start > earlier.train_start

    def test_embargo_gaps_are_enforced(self, result: Any) -> None:
        for fold in result.folds:
            gap_periods = pd.Timestamp(fold.test_start) - pd.Timestamp(fold.train_end)
            assert gap_periods > pd.Timedelta(0)

    def test_pooled_oos_and_degradation_present(self, result: Any) -> None:
        assert result.pooled_oos_metrics["periods"] == sum(
            fold.test_periods for fold in result.folds
        )
        assert result.degradation_ratio is not None
        assert result.verdict_hint in {"consistent", "degraded", "fragile", "inconclusive"}

    def test_deterministic_across_runs(self, result: Any) -> None:
        bundle = _wf_bundle()
        engine = BacktestEngine(
            BacktestConfig(
                rebalance=RebalanceFrequency.WEEKLY,
                top_k=2,
                max_weight=0.55,
                benchmark_symbol="DEMO-BENCH",
                seed=23,
            )
        )
        settings = WalkForwardConfig(train_periods=40, test_periods=12, embargo_periods=2)
        again = walk_forward(bundle, PriceOnlyMomentum(momentum_sessions=21), engine, settings)
        assert result.to_dict() == again.to_dict()

    def test_insufficient_history_raises(self) -> None:
        tiny = _wf_bundle(120)
        engine = BacktestEngine(BacktestConfig(rebalance=RebalanceFrequency.WEEKLY))
        with pytest.raises(InsufficientDataError, match="rebalance decisions"):
            walk_forward(tiny, PriceOnlyMomentum(momentum_sessions=21), engine, WalkForwardConfig())

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError, match="training"):
            WalkForwardConfig(train_periods=2)
        with pytest.raises(ValueError, match="testing"):
            WalkForwardConfig(test_periods=1)
        with pytest.raises(ValueError, match="embargo"):
            WalkForwardConfig(embargo_periods=-1)

    def test_to_dict_shape(self, result: Any) -> None:
        payload = result.to_dict()
        assert payload["verdict_hint"] == result.verdict_hint
        assert len(payload["folds"]) == len(result.folds)
        json.dumps(payload)


# ---------------------------------------------------------------------------
# Upgrade 6 + 5: timings and JSON CLI surface


class TestCliUpgrades:
    def test_demo_manifest_contains_timings(self) -> None:
        outcome = run_synthetic_demo(sessions=180, seed=7, fast_audit=True)
        timings = outcome.result.manifest.get("timings")
        assert isinstance(timings, dict)
        assert timings["backtest_seconds"] >= 0
        assert timings["audit_seconds"] >= 0

    def test_backtest_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:

        project = tmp_path / "proj"
        project.mkdir()
        _write_csv_project(project)
        runner = CliRunner()
        result = runner.invoke(
            app, ["backtest", "--config", str(project / "alphaverdict.yml"), "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["verdict"] in {"pass", "warn", "fail"}
        assert isinstance(payload["findings"], list)
        assert payload["report_path"]

    def test_walkforward_cli_writes_artifact(self, tmp_path: Path) -> None:

        project = tmp_path / "proj"
        project.mkdir()
        rows = _csv_rows(700)
        (project / "prices.csv").write_text(rows, encoding="utf-8")
        (project / "strategy.py").write_text(_STRATEGY_SOURCE, encoding="utf-8")
        (project / "alphaverdict.yml").write_text(_PROJECT_YAML, encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "walkforward",
                "--config",
                str(project / "alphaverdict.yml"),
                "--train",
                "30",
                "--test",
                "10",
                "--embargo",
                "2",
            ],
        )
        assert result.exit_code == 0, result.output
        artifact = project / "runs" / "walkforward.json"
        assert artifact.is_file()
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["config"]["embargo_periods"] == 2


_CSV_HEADER = "symbol,timestamp,open,high,low,close,volume,source"


def _csv_rows(sessions: int, symbols: tuple[str, ...] = ("AAA", "BBB", "CCC")) -> str:
    dates = pd.bdate_range("2022-01-03", periods=sessions)
    lines = [_CSV_HEADER]
    for position, symbol in enumerate(symbols):
        drift = 0.0009 - position * 0.0004
        closes = 50.0 * np.exp(np.cumsum(np.full(sessions, drift)))
        for date, close in zip(dates, closes, strict=True):
            lines.append(
                f"{symbol},{date.isoformat()},{close - 1:.4f},{close + 1:.4f},"
                f"{close - 2:.4f},{close:.4f},1000,fixture"
            )
    for date, close in zip(dates, np.linspace(150, 190, sessions), strict=True):
        lines.append(
            f"BENCH,{date.isoformat()},{close:.4f},{close:.4f},{close:.4f},{close:.4f},1000,fixture"
        )
    return "\n".join(lines) + "\n"


_STRATEGY_SOURCE = '''
"""Fixture momentum strategy."""
from dataclasses import dataclass

import pandas as pd

from alphaverdict import ResearchSnapshot, StockStrategy


@dataclass
class CsvMomentum(StockStrategy):
    name = "csv-momentum"
    minimum_history = 30
    lookback: int = 21

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        scores = snapshot.trailing_momentum(self.lookback)
        symbols = [s for s in snapshot.universe if s != "BENCH"]
        frame = pd.DataFrame(index=pd.Index(sorted(set(symbols)), name="symbol"))
        frame["score"] = pd.to_numeric(scores.reindex(frame.index), errors="coerce")
        frame["eligible"] = frame["score"].notna()
        frame["rationale"] = "fixture momentum"
        return frame.reset_index()[["symbol", "score", "eligible", "rationale"]]
'''

_PROJECT_YAML = """version: 1
data:
  adapter: csv
  options:
    prices: prices.csv
strategy: strategy.py:CsvMomentum
screen:
  top_n: 3
backtest:
  rebalance: weekly
  top_k: 2
  max_weight: 0.6
  benchmark_symbol: BENCH
audit:
  bootstrap_simulations: 100
  permutation_simulations: 100
  causality_cutoffs: 2
  stability_folds: 2
output_dir: runs
"""


def _write_csv_project(project: Path, sessions: int = 400) -> None:
    (project / "prices.csv").write_text(_csv_rows(sessions), encoding="utf-8")
    (project / "strategy.py").write_text(_STRATEGY_SOURCE, encoding="utf-8")
    (project / "alphaverdict.yml").write_text(_PROJECT_YAML, encoding="utf-8")
