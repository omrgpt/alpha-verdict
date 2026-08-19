"""Typed configuration objects with explicit runtime construction."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alphaverdict.audit.models import AuditConfig
from alphaverdict.data.adapter import DataAdapter
from alphaverdict.data.contracts import DataKind, DataRequest
from alphaverdict.data.registry import adapter_class
from alphaverdict.engine.backtest import BacktestEngine
from alphaverdict.engine.models import BacktestConfig
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.loader import load_strategy
from alphaverdict.utils import resolve_within


@dataclass(frozen=True, slots=True)
class DataConfig:
    """A provider adapter and its user-owned options."""

    adapter: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScreenConfig:
    """Defaults for a one-date ranking."""

    top_n: int = 20
    minimum_score: float | None = None

    def __post_init__(self) -> None:
        if self.top_n <= 0:
            raise ValueError("screen.top_n must be positive")


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Complete, portable AlphaVerdict project specification."""

    root: Path
    data: DataConfig
    strategy: str
    request: DataRequest = field(default_factory=DataRequest)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    output_dir: str = "runs"
    allow_outside_root: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())
        resolve_within(self.root, self.output_dir, allow_outside=self.allow_outside_root)

    @property
    def output_path(self) -> Path:
        return resolve_within(
            self.root,
            self.output_dir,
            allow_outside=self.allow_outside_root,
        )

    def make_adapter(self) -> DataAdapter:
        """Instantiate the explicitly named adapter.

        Adapter and strategy plugins execute trusted local Python. Config files
        from untrusted repositories must be reviewed before running them.
        """
        options = dict(self.data.options)
        candidate_class = adapter_class(self.data.adapter)
        parameters = inspect.signature(candidate_class).parameters
        if "root" in parameters:
            options.setdefault("root", self.root)
        if "allow_outside_root" in parameters:
            options.setdefault("allow_outside_root", self.allow_outside_root)
        candidate = candidate_class(**options)
        return candidate

    def make_strategy(self) -> StockStrategy:
        return load_strategy(
            self.strategy,
            root=self.root,
            allow_outside_root=self.allow_outside_root,
        )

    def make_engine(self) -> BacktestEngine:
        return BacktestEngine(self.backtest)

    @property
    def requested_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(kind.value for kind in self.request.kinds))


def data_request_from_dict(values: dict[str, Any]) -> DataRequest:
    kinds = values.get("kinds", tuple(kind.value for kind in DataKind))
    return DataRequest(
        start=values.get("start"),
        end=values.get("end"),
        symbols=tuple(values.get("symbols", ())),
        kinds=frozenset(DataKind(item) for item in kinds),
    )
