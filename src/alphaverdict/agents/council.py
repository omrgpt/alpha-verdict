"""Concurrent deterministic review council with stable merge semantics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from alphaverdict.agents.base import AuditContext, ReviewAgent
from alphaverdict.agents.builtin import (
    CausalityAgent,
    DataIntegrityAgent,
    PerformanceAgent,
    RobustnessAgent,
    StatisticalAgent,
    TrialsAgent,
)
from alphaverdict.audit.models import AuditConfig, AuditReport, Severity, Verdict
from alphaverdict.audit.recommendations import recommendations_for
from alphaverdict.data.bundle import DataBundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestResult
from alphaverdict.strategy.base import StockStrategy


class AuditCouncil:
    """Run independent read-only reviewers and merge evidence deterministically."""

    def __init__(
        self,
        agents: tuple[ReviewAgent, ...] | None = None,
        *,
        trials_ledger_path: str | None = None,
    ) -> None:
        self.agents = agents or (
            DataIntegrityAgent(),
            CausalityAgent(),
            PerformanceAgent(),
            RobustnessAgent(),
            StatisticalAgent(),
            TrialsAgent(ledger_path=trials_ledger_path),
        )

    def review(
        self,
        bundle: DataBundle,
        strategy: StockStrategy,
        engine: BacktestEngine,
        result: BacktestResult,
        config: AuditConfig | None = None,
    ) -> AuditReport:
        settings = config or AuditConfig(seed=result.config.seed)
        context = AuditContext(bundle, strategy, engine, result, settings)
        with ThreadPoolExecutor(
            max_workers=len(self.agents), thread_name_prefix="alphaverdict-audit"
        ) as pool:
            reports = tuple(pool.map(lambda agent: agent.review(context), self.agents))
        reports = tuple(sorted(reports, key=lambda item: item.agent))
        findings = tuple(
            sorted(
                (finding for report in reports for finding in report.findings),
                key=lambda item: (-int(item.severity), item.code, item.agent),
            )
        )
        penalties = {
            Severity.CRITICAL: 35,
            Severity.HIGH: 15,
            Severity.MEDIUM: 7,
            Severity.LOW: 2,
            Severity.INFO: 0,
        }
        score = max(0, 100 - sum(penalties[finding.severity] for finding in findings))
        if any(finding.severity is Severity.CRITICAL for finding in findings) or score < 40:
            verdict = Verdict.FAIL
        elif any(finding.severity >= Severity.HIGH for finding in findings) or score < 75:
            verdict = Verdict.WARN
        else:
            verdict = Verdict.PASS
        return AuditReport(
            verdict=verdict,
            score=score,
            findings=findings,
            agent_reports=reports,
            recommendations=recommendations_for(findings),
            caveat=(
                "A pass means only that this run survived the configured tests. It is not evidence of future "
                "returns, a recommendation, or permission to deploy capital."
            ),
        )
