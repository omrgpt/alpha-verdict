"""Agent protocol; built-ins are deterministic and require no model key."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from alphaverdict.audit.models import AgentReport, AuditConfig
from alphaverdict.data.bundle import DataBundle
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestResult
from alphaverdict.strategy.base import StockStrategy


@dataclass(frozen=True)
class AuditContext:
    bundle: DataBundle
    strategy: StockStrategy
    engine: BacktestEngine
    result: BacktestResult
    config: AuditConfig


class ReviewAgent(Protocol):
    name: str

    def review(self, context: AuditContext) -> AgentReport:
        """Inspect immutable evidence and return bounded findings."""
        ...
