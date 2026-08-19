"""Adapter protocol used by private and third-party data connectors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataRequest


class HealthStatus(StrEnum):
    # This is a public health value, not a credential.
    PASS = "pass"  # nosec B105
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class AdapterHealth:
    """A side-effect-free readiness result for a data adapter."""

    name: str
    status: HealthStatus
    detail: str


@runtime_checkable
class DataAdapter(Protocol):
    """Minimal contract every user-owned data adapter implements."""

    name: str

    def load(self, request: DataRequest) -> DataBundle:
        """Load a canonical, point-in-time bundle."""
        ...

    def health(self) -> AdapterHealth:
        """Check configuration without downloading or mutating data."""
        ...
