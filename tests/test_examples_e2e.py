"""End-to-end tests: runnable example gallery + demo theater."""

from __future__ import annotations

import json
from pathlib import Path

from alphaverdict.agents.council import AuditCouncil
from alphaverdict.config.reader import load_project
from alphaverdict.demo import (
    DemoEvidenceStrategy,
    run_corrupted_demo,
    run_synthetic_demo,
    synthetic_bundle,
)
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig
from alphaverdict.report.render import write_run_report

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "quickstart"


def test_example_project_is_present_and_self_contained() -> None:
    assert (EXAMPLES / "alphaverdict.yml").is_file()
    assert (EXAMPLES / "strategy.py").is_file()
    for name in ("prices", "fundamentals", "events", "universe"):
        assert (EXAMPLES / "data" / f"{name}.csv").is_file(), name
    readme = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    assert "alphaverdict backtest" in readme


def test_example_strategy_is_multimodal() -> None:
    source = (EXAMPLES / "strategy.py").read_text(encoding="utf-8")
    # must genuinely combine three data types, not just prices
    assert "latest_features" in source, "fundamentals pillar missing"
    assert "known_events" in source, "news/events pillar missing"
    assert "close_matrix" in source or "trailing_momentum" in source


def test_example_backtest_runs_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """The gallery promise: cd examples/quickstart && alphaverdict backtest works."""
    monkeypatch.chdir(EXAMPLES)
    project = load_project("alphaverdict.yml")
    bundle = project.make_adapter().load(project.request)
    strategy = project.make_strategy()
    engine = BacktestEngine(project.backtest)
    result = engine.run(bundle, strategy)
    audit = AuditCouncil(trials_ledger_path=str(tmp_path / "t.jsonl")).review(
        bundle, strategy, engine, result, project.audit
    )
    artifacts = write_run_report(result, audit, tmp_path)
    assert artifacts.report.is_file()
    payload = json.loads(artifacts.audit.read_text(encoding="utf-8"))
    assert "diagnoses" in payload and isinstance(payload["diagnoses"], list)


def test_corrupted_demo_twin_is_caught(tmp_path: Path) -> None:
    outcome = run_corrupted_demo(tmp_path / "corrupt", seed=7, sessions=260)
    codes = {finding.code for finding in outcome.audit.findings}
    assert "DATA_TEMPORAL_LEAK" in codes


def test_demo_twins_diverge_on_score(tmp_path: Path) -> None:
    """The theater's core claim: honest vs corrupted data produce different outcomes."""
    honest = run_synthetic_demo(tmp_path / "honest", seed=7, sessions=260, fast_audit=True)
    corrupted = run_corrupted_demo(tmp_path / "corrupt", seed=7, sessions=260)
    leak_caught = any(finding.code == "DATA_TEMPORAL_LEAK" for finding in corrupted.audit.findings)
    diverged = corrupted.audit.score != honest.audit.score
    assert leak_caught and diverged, "corrupted twin must be caught and must score differently"


def test_diagnoses_appear_in_html_report(tmp_path: Path) -> None:
    bundle = synthetic_bundle(seed=11, sessions=300)
    strategy = DemoEvidenceStrategy(momentum_sessions=30)
    engine = BacktestEngine(
        BacktestConfig(
            rebalance="weekly", top_k=3, max_weight=0.40, benchmark_symbol="DEMO-BENCH", seed=11
        )
    )
    result = engine.run(bundle, strategy)
    audit = AuditCouncil().review(bundle, strategy, engine, result)
    artifacts = write_run_report(result, audit, tmp_path)
    html = artifacts.report.read_text(encoding="utf-8")
    if audit.diagnoses:
        assert "Diagnosed next experiments" in html
        assert "What held up" in html
