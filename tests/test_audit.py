"""Adversarial review, statistics, and recommendation tests."""

from __future__ import annotations

import pandas as pd
import pytest

from alphaverdict.agents.base import AuditContext
from alphaverdict.agents.builtin import (
    CausalityAgent,
    DataIntegrityAgent,
    PerformanceAgent,
    RobustnessAgent,
    StatisticalAgent,
)
from alphaverdict.agents.council import AuditCouncil
from alphaverdict.agents.llm import BoundedNarrativeReviewer
from alphaverdict.audit.models import (
    AgentReport,
    AuditConfig,
    AuditReport,
    Finding,
    Severity,
    Verdict,
)
from alphaverdict.audit.recommendations import recommendations_for
from alphaverdict.audit.statistics import (
    block_bootstrap,
    deflated_sharpe_probability,
    expected_max_sharpe,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    sample_sharpe,
    sign_flip_test,
)


def test_statistical_diagnostics_are_deterministic_and_bounded() -> None:
    values = pd.Series([0.01, -0.005, 0.015, 0.002, -0.003] * 12)
    assert sample_sharpe(values) > 0
    assert 0 <= probabilistic_sharpe_ratio(values) <= 1
    assert expected_max_sharpe(values, 1) == 0
    assert expected_max_sharpe(values, 20) > 0
    assert 0 <= deflated_sharpe_probability(values, 20) <= 1
    assert minimum_track_record_length(values) is not None
    assert minimum_track_record_length(-values.abs()) is None
    first = sign_flip_test(values, 200, 3)
    assert first == sign_flip_test(values, 200, 3)
    assert 0 <= first["p_value"] <= 1
    bootstrap = block_bootstrap(
        values,
        simulations=200,
        block_size=5,
        confidence=0.95,
        seed=3,
    )
    assert bootstrap["simulations"] == 200
    assert 0 <= bootstrap["probability_positive"] <= 1


def test_statistics_short_sample_boundaries() -> None:
    empty = pd.Series(dtype=float)
    one = pd.Series([0.1])
    assert sample_sharpe(one) == 0
    assert probabilistic_sharpe_ratio(one) == 0.5
    assert minimum_track_record_length(one) is None
    assert sign_flip_test(one, 100, 1)["p_value"] == 1
    assert (
        block_bootstrap(empty, simulations=100, block_size=2, confidence=0.9, seed=1)["simulations"]
        == 0
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_trials": 0},
        {"bootstrap_simulations": 99},
        {"permutation_simulations": 99},
        {"bootstrap_block_size": 0},
        {"confidence": 0.5},
        {"cost_multipliers": ()},
        {"causality_cutoffs": 0},
        {"stability_folds": 1},
    ],
)
def test_audit_config_rejects_invalid_thresholds(kwargs) -> None:
    with pytest.raises(ValueError):
        AuditConfig(**kwargs)


def test_every_builtin_agent_returns_machine_readable_evidence(
    demo_bundle,
    demo_strategy,
    demo_engine,
    demo_result,
) -> None:
    config = AuditConfig(
        bootstrap_simulations=100,
        permutation_simulations=100,
        cost_multipliers=(1.0,),
        stability_folds=3,
        causality_cutoffs=2,
        seed=11,
    )
    context = AuditContext(demo_bundle, demo_strategy, demo_engine, demo_result, config)
    for agent in (
        DataIntegrityAgent(),
        CausalityAgent(),
        PerformanceAgent(),
        RobustnessAgent(),
        StatisticalAgent(),
    ):
        report = agent.review(context)
        assert report.agent == agent.name
        assert report.summary
        assert report.to_dict()["agent"] == agent.name


def test_data_integrity_agent_detects_impossible_prices(
    demo_bundle,
    demo_strategy,
    demo_engine,
    demo_result,
) -> None:
    prices = demo_bundle.prices.copy()
    prices.loc[0, "high"] = prices.loc[0, "low"] - 1
    corrupt = demo_bundle.with_prices(prices)
    context = AuditContext(
        corrupt,
        demo_strategy,
        demo_engine,
        demo_result,
        AuditConfig(bootstrap_simulations=100, permutation_simulations=100),
    )
    report = DataIntegrityAgent().review(context)
    assert any(item.code == "DATA_PRICE_INVARIANT" for item in report.findings)


class FixedAgent:
    def __init__(self, severity: Severity) -> None:
        self.name = f"fixed-{severity.label}"
        self.severity = severity

    def review(self, context: AuditContext) -> AgentReport:
        finding = Finding(
            code="FIXED",
            severity=self.severity,
            title="Bounded test finding",
            evidence="test evidence",
            recommendation="test next step",
            agent=self.name,
        )
        return AgentReport(self.name, "fixed", (finding,))


@pytest.mark.parametrize(
    ("severity", "verdict"),
    [
        (Severity.INFO, Verdict.PASS),
        (Severity.HIGH, Verdict.WARN),
        (Severity.CRITICAL, Verdict.FAIL),
    ],
)
def test_council_merges_findings_into_stable_verdict(
    demo_bundle,
    demo_strategy,
    demo_engine,
    demo_result,
    severity: Severity,
    verdict: Verdict,
) -> None:
    report = AuditCouncil((FixedAgent(severity),)).review(
        demo_bundle,
        demo_strategy,
        demo_engine,
        demo_result,
        AuditConfig(bootstrap_simulations=100, permutation_simulations=100),
    )
    assert report.verdict is verdict
    assert report.findings[0].severity is severity
    assert report.to_dict()["score"] == report.score


def test_recommendations_are_deduplicated_and_limited() -> None:
    findings = tuple(
        Finding("COST_FRAGILE", Severity.HIGH, "x", "x", "fallback", f"agent-{index}")
        for index in range(10)
    )
    assert len(recommendations_for(findings)) == 1
    custom = (Finding("CUSTOM", Severity.LOW, "x", "x", "custom step", "agent"),)
    assert recommendations_for(custom) == ("custom step",)


def test_bounded_narrative_reviewer_never_receives_raw_inputs() -> None:
    observed: list[str] = []
    report = AuditReport(Verdict.PASS, 100, (), (), (), "caveat")

    def invoke(prompt: str) -> str:
        observed.append(prompt)
        return "summary" * 20

    reviewer = BoundedNarrativeReviewer(invoke, maximum_characters=12)
    assert reviewer.summarize(report) == "summarysumma"
    assert "caveat" in observed[0] and "price" not in observed[0].lower()
    with pytest.raises(ValueError, match="empty"):
        BoundedNarrativeReviewer(lambda _: "").summarize(report)
