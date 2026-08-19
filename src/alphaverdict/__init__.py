"""AlphaVerdict public API.

AlphaVerdict is research infrastructure. It does not place orders, connect to
brokerage accounts, or provide investment advice.
"""

from alphaverdict._version import __version__
from alphaverdict.agents.council import AuditCouncil
from alphaverdict.audit.models import AuditConfig, AuditReport
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataRequest
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig
from alphaverdict.engine.screen import screen
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot
from alphaverdict.strategy.signals import SignalSet

__all__ = [
    "AuditConfig",
    "AuditCouncil",
    "AuditReport",
    "BacktestConfig",
    "BacktestEngine",
    "DataBundle",
    "DataRequest",
    "ResearchSnapshot",
    "SignalSet",
    "StockStrategy",
    "__version__",
    "screen",
]
