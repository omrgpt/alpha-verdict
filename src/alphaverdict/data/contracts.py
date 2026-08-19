"""Canonical schemas for provider-neutral stock research data."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import pandas as pd

from alphaverdict.exceptions import DataContractError


class DataKind(StrEnum):
    """Data families understood by the temporal research store."""

    PRICES = "prices"
    FEATURES = "features"
    EVENTS = "events"
    UNIVERSE = "universe"


PRICE_COLUMNS = ("symbol", "timestamp", "open", "high", "low", "close", "volume", "source")
FEATURE_COLUMNS = (
    "symbol",
    "observed_at",
    "available_at",
    "feature",
    "value",
    "source",
    "revision",
)
EVENT_COLUMNS = (
    "symbol",
    "event_at",
    "available_at",
    "event_type",
    "payload",
    "source",
)
UNIVERSE_COLUMNS = (
    "symbol",
    "effective_from",
    "effective_to",
    "available_at",
    "source",
)


@dataclass(frozen=True, slots=True)
class DataRequest:
    """A bounded request passed to user-supplied adapters."""

    start: pd.Timestamp | str | None = None
    end: pd.Timestamp | str | None = None
    symbols: tuple[str, ...] = ()
    kinds: frozenset[DataKind] = field(default_factory=lambda: frozenset(DataKind))

    def __post_init__(self) -> None:
        start = _timestamp(self.start) if self.start is not None else None
        end = _timestamp(self.end) if self.end is not None else None
        if start is not None and end is not None and start > end:
            raise DataContractError("data request start must not be after end")
        normalized = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in self.symbols if symbol.strip())
        )
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "symbols", normalized)


def _timestamp(value: Any) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise DataContractError(f"invalid timestamp: {value!r}") from exc
    if pd.isna(timestamp):
        raise DataContractError(f"invalid timestamp: {value!r}")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=list(PRICE_COLUMNS))


def empty_features() -> pd.DataFrame:
    return pd.DataFrame(columns=list(FEATURE_COLUMNS))


def empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=list(EVENT_COLUMNS))


def empty_universe() -> pd.DataFrame:
    return pd.DataFrame(columns=list(UNIVERSE_COLUMNS))


def require_columns(frame: pd.DataFrame, required: tuple[str, ...], kind: DataKind) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise DataContractError(f"{kind.value} data is missing columns: {', '.join(missing)}")
