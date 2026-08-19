"""Stable schemas shared by audit agents and report renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

from alphaverdict.utils import _json_safe


class Severity(IntEnum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return self.name.lower()


class Verdict(StrEnum):
    # This is a public verdict value, not a credential.
    PASS = "pass"  # nosec B105
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Finding:
    """One bounded, source-labelled audit conclusion."""

    code: str
    severity: Severity
    title: str
    evidence: str
    recommendation: str
    agent: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.label,
            "title": self.title,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "agent": self.agent,
            "metrics": _json_safe(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class AuditConfig:
    """Bounded deterministic settings for the research audit."""

    n_trials: int = 1
    bootstrap_simulations: int = 500
    bootstrap_block_size: int = 5
    permutation_simulations: int = 500
    confidence: float = 0.95
    cost_multipliers: tuple[float, ...] = (0.0, 1.0, 2.0, 5.0)
    causality_cutoffs: int = 3
    stability_folds: int = 4
    minimum_periods: int = 24
    seed: int = 7

    def __post_init__(self) -> None:
        if self.n_trials <= 0:
            raise ValueError("n_trials must be positive")
        if self.bootstrap_simulations < 100 or self.permutation_simulations < 100:
            raise ValueError("statistical simulations must be at least 100")
        if self.bootstrap_block_size <= 0:
            raise ValueError("bootstrap block size must be positive")
        if not 0.5 < self.confidence < 1:
            raise ValueError("confidence must be in (0.5, 1)")
        if not self.cost_multipliers or any(value < 0 for value in self.cost_multipliers):
            raise ValueError("cost multipliers must be non-empty and non-negative")
        if self.causality_cutoffs <= 0 or self.stability_folds < 2:
            raise ValueError("causality cutoffs and stability folds must be positive")


@dataclass(frozen=True)
class AgentReport:
    agent: str
    summary: str
    findings: tuple[Finding, ...]
    measurements: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "measurements": _json_safe(self.measurements),
        }


@dataclass(frozen=True)
class AuditReport:
    """Merged verdict from independent, deterministic review agents."""

    verdict: Verdict
    score: int
    findings: tuple[Finding, ...]
    agent_reports: tuple[AgentReport, ...]
    recommendations: tuple[str, ...]
    caveat: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "score": self.score,
            "caveat": self.caveat,
            "recommendations": list(self.recommendations),
            "findings": [finding.to_dict() for finding in self.findings],
            "agents": [report.to_dict() for report in self.agent_reports],
        }
