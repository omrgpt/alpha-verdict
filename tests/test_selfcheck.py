"""Tests for the adversarial bias zoo (Self-Check) and the TrialsAgent."""

from __future__ import annotations

from pathlib import Path

from alphaverdict.agents.base import AuditContext
from alphaverdict.agents.builtin import TrialsAgent
from alphaverdict.audit.ledger import TrialLedger
from alphaverdict.audit.models import AuditConfig, Severity
from alphaverdict.demo import DemoEvidenceStrategy, synthetic_bundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig, RebalanceFrequency
from alphaverdict.selfcheck.zoo import CASES, run_self_check


def test_zoo_catches_every_planted_trap() -> None:
    """The council must detect all bias fixtures; this is Self-Check's contract."""
    missed = run_self_check(print_fn=lambda _message: None)
    assert missed == []


def test_zoo_registry_has_expected_coverage() -> None:
    names = [name for name, _case in CASES]
    assert len(names) >= 8
    assert "lookahead-metadata-smuggling" in names
    assert "frozen-warmup-state" in names
    assert "ledger-tampering-detected" in names
    assert "underdeclared-trials" in names


def _context(ledger_path: Path | None, n_trials: int = 1):
    bundle = synthetic_bundle(seed=11, sessions=180)
    strategy = DemoEvidenceStrategy(momentum_sessions=30)
    engine = BacktestEngine(
        BacktestConfig(
            rebalance=RebalanceFrequency.WEEKLY,
            top_k=3,
            max_weight=0.40,
            benchmark_symbol="DEMO-BENCH",
            seed=11,
        )
    )
    result = engine.run(bundle, strategy)
    config = AuditConfig(
        bootstrap_simulations=100,
        permutation_simulations=100,
        cost_multipliers=(1.0,),
        stability_folds=2,
        causality_cutoffs=2,
        n_trials=n_trials,
        seed=11,
    )
    return AuditContext(bundle, strategy, engine, result, config)


def test_trials_agent_flags_missing_ledger(tmp_path: Path) -> None:
    context = _context(None)
    agent = TrialsAgent(ledger_path=str(tmp_path / "absent.jsonl"))
    report = agent.review(context)
    codes = {finding.code for finding in report.findings}
    assert "TRIALS_LEDGER_MISSING" in codes
    assert any(finding.severity is Severity.MEDIUM for finding in report.findings)


def test_trials_agent_accepts_matching_burden(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    ledger = TrialLedger(path)
    stub = type(
        "S",
        (),
        {
            "manifest": {},
            "strategy_name": "s",
            "strategy_fingerprint": "fp-1",
            "data_fingerprint": "d",
        },
    )()
    ledger.record_result(stub)
    context = _context(path, n_trials=1)
    report = TrialsAgent(ledger_path=str(path)).review(context)
    codes = {finding.code for finding in report.findings}
    assert "TRIALS_UNDERDECLARED" not in codes
    assert "TRIALS_LEDGER_TAMPERED" not in codes
    assert report.measurements["chain_intact"] is True


def test_trials_agent_flags_underdeclaration(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    ledger = TrialLedger(path)
    for fingerprint in ("fp-1", "fp-2", "fp-3"):
        stub = type(
            "S",
            (),
            {
                "manifest": {},
                "strategy_name": fingerprint,
                "strategy_fingerprint": fingerprint,
                "data_fingerprint": "d",
            },
        )()
        ledger.record_result(stub)
    context = _context(path, n_trials=1)
    report = TrialsAgent(ledger_path=str(path)).review(context)
    flagged = [finding for finding in report.findings if finding.code == "TRIALS_UNDERDECLARED"]
    assert flagged and flagged[0].metrics["recorded_variants"] == 3
