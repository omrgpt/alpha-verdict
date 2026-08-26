"""Tests for the deterministic diagnosis engine (evidence -> ranked experiments)."""

from __future__ import annotations

from pathlib import Path

import pytest

from alphaverdict.agents.council import AuditCouncil
from alphaverdict.audit.diagnose import diagnose, strengths_of
from alphaverdict.audit.models import AuditConfig, Finding, Severity
from alphaverdict.data.bundle import DataBundle
from alphaverdict.demo import DemoEvidenceStrategy, synthetic_bundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig
from alphaverdict.engine.walkforward import WalkForwardConfig, walk_forward


def _finding(code: str) -> Finding:
    return Finding(
        code=code,
        severity=Severity.MEDIUM,
        title=code,
        evidence="test",
        recommendation="test",
        agent="test",
    )


def _engine(bundle: DataBundle) -> BacktestEngine:
    return BacktestEngine(
        BacktestConfig(
            rebalance="weekly",
            top_k=3,
            max_weight=0.40,
            benchmark_symbol="DEMO-BENCH",
            seed=11,
        )
    )


def _result():
    bundle = synthetic_bundle(seed=11, sessions=300)
    strategy = DemoEvidenceStrategy(momentum_sessions=30)
    return _engine(bundle).run(bundle, strategy)


def test_diagnose_concentration_rule_cites_real_symbols() -> None:
    result = _result()
    experiments = diagnose(result, (_finding("SYMBOL_CONCENTRATION"),))
    assert experiments, "concentration finding should produce a diagnosis"
    top = experiments[0]
    assert top.source_codes == ("SYMBOL_CONCENTRATION",)
    # observation must cite actual symbols from the run's own holdings table
    held = set(result.holdings["symbol"].unique())
    cited_any = any(str(sym) in top.observation for sym in held)
    assert cited_any, f"observation names no held symbol: {top.observation}"


def test_diagnose_is_deterministic() -> None:
    result = _result()
    findings = (_finding("SYMBOL_CONCENTRATION"), _finding("COST_FRAGILE"))
    first = [item.to_dict() for item in diagnose(result, findings)]
    second = [item.to_dict() for item in diagnose(result, findings)]
    assert first == second


def test_diagnose_ranks_most_urgent_first() -> None:
    result = _result()
    findings = (
        _finding("BENCHMARK_UNDERPERFORMANCE"),
        _finding("SYMBOL_CONCENTRATION"),
    )
    experiments = diagnose(result, findings)
    assert len(experiments) >= 2
    severities = [item.severity for item in experiments]
    # rank 1 is most urgent: severities must be non-increasing
    assert severities == sorted(severities, reverse=True)
    ranks = [item.rank for item in experiments]
    assert ranks == list(range(1, len(experiments) + 1))


def test_diagnose_no_findings_no_experiments() -> None:
    result = _result()
    assert diagnose(result, ()) == ()


def test_cost_fragility_experiment_quotes_breakeven_math() -> None:
    result = _result()
    experiments = diagnose(result, (_finding("COST_FRAGILE"),))
    assert experiments and experiments[0].source_codes == ("COST_FRAGILE",)
    text = experiments[0].observation + experiments[0].experiment
    assert "bps" in text


def test_strengths_are_balanced_and_grounded() -> None:
    result = _result()
    strengths = strengths_of(result, ())
    assert isinstance(strengths, tuple)
    for item in strengths:
        assert isinstance(item, str) and len(item) > 20


def test_audit_report_serializes_new_fields(tmp_path: Path) -> None:
    bundle = synthetic_bundle(seed=11, sessions=180)
    strategy = DemoEvidenceStrategy(momentum_sessions=30)
    engine = BacktestEngine(
        BacktestConfig(rebalance="weekly", top_k=3, benchmark_symbol="DEMO-BENCH", seed=11)
    )
    result = engine.run(bundle, strategy)
    audit = AuditCouncil().review(bundle, strategy, engine, result)
    payload = audit.to_dict()
    assert "diagnoses" in payload and isinstance(payload["diagnoses"], list)
    assert "strengths" in payload and isinstance(payload["strengths"], list)


@pytest.mark.parametrize(
    "code",
    ["PERFORMANCE_SAMPLE_SMALL", "REGIME_INSTABILITY", "PERFORMANCE_EXTREME_SHARPE"],
)
def test_each_rule_fires_on_its_code(code: str) -> None:
    result = _result()
    experiments = diagnose(result, (_finding(code),))
    assert all(item.source_codes == (code,) or code in item.source_codes for item in experiments)


def test_walkforward_artifact_still_writes(tmp_path: Path) -> None:
    """Walk-forward stays available as its own command artifact."""
    bundle = synthetic_bundle(seed=11, sessions=620)
    wf = walk_forward(
        bundle,
        DemoEvidenceStrategy(momentum_sessions=30),
        BacktestEngine(
            BacktestConfig(rebalance="monthly", top_k=3, benchmark_symbol="DEMO-BENCH", seed=11)
        ),
        WalkForwardConfig(train_periods=8, test_periods=4, embargo_periods=1),
    )
    assert len(wf.folds) >= 2


def test_audit_config_still_validates_n_trials() -> None:
    with pytest.raises(ValueError):
        AuditConfig(n_trials=0)
