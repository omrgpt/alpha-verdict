"""Bitemporal, provider-neutral data container."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

import pandas as pd

from alphaverdict.data.contracts import (
    EVENT_COLUMNS,
    FEATURE_COLUMNS,
    PRICE_COLUMNS,
    UNIVERSE_COLUMNS,
    DataKind,
    DataRequest,
    _timestamp,
    empty_events,
    empty_features,
    empty_prices,
    empty_universe,
    require_columns,
)
from alphaverdict.exceptions import DataContractError
from alphaverdict.utils import canonical_json, hash_dataframe, sha256_text


def _symbols(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip().str.upper()
    if values.isna().any() or (values == "").any():
        raise DataContractError("symbols must be non-empty")
    return values


def _times(series: pd.Series, name: str, *, nullable: bool = False) -> pd.Series:
    values = pd.to_datetime(series, utc=True, errors="coerce")
    if not nullable and values.isna().any():
        raise DataContractError(f"{name} contains invalid or missing timestamps")
    return values


def _sources(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    if values.isna().any() or (values == "").any():
        raise DataContractError("every row must identify a non-empty source")
    return values


def _normalize_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty and not set(PRICE_COLUMNS).issubset(frame.columns):
        return empty_prices()
    require_columns(frame, PRICE_COLUMNS, DataKind.PRICES)
    result = frame.copy()
    result["symbol"] = _symbols(result["symbol"])
    result["timestamp"] = _times(result["timestamp"], "timestamp")
    result["source"] = _sources(result["source"])
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result[["open", "high", "low", "close"]].isna().any().any():
        raise DataContractError("prices contain non-numeric OHLC values")
    duplicate = result.duplicated(["symbol", "timestamp"], keep=False)
    if duplicate.any():
        raise DataContractError("prices contain duplicate symbol/timestamp rows")
    return result.sort_values(["timestamp", "symbol"], kind="stable").reset_index(drop=True)


def _normalize_features(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty and not set(FEATURE_COLUMNS).issubset(frame.columns):
        return empty_features()
    result = frame.copy()
    if "revision" not in result:
        result["revision"] = 0
    require_columns(result, FEATURE_COLUMNS, DataKind.FEATURES)
    result["symbol"] = _symbols(result["symbol"])
    result["observed_at"] = _times(result["observed_at"], "observed_at")
    result["available_at"] = _times(result["available_at"], "available_at")
    result["feature"] = result["feature"].astype("string").str.strip()
    result["source"] = _sources(result["source"])
    result["revision"] = pd.to_numeric(result["revision"], errors="raise").astype(int)
    if (result["feature"] == "").any():
        raise DataContractError("feature names must be non-empty")
    duplicate = result.duplicated(
        ["symbol", "observed_at", "available_at", "feature", "revision"], keep=False
    )
    if duplicate.any():
        raise DataContractError("features contain duplicate bitemporal keys")
    return result.sort_values(
        ["available_at", "observed_at", "symbol", "feature", "revision"], kind="stable"
    ).reset_index(drop=True)


def _normalize_events(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty and not set(EVENT_COLUMNS).issubset(frame.columns):
        return empty_events()
    require_columns(frame, EVENT_COLUMNS, DataKind.EVENTS)
    result = frame.copy()
    result["symbol"] = _symbols(result["symbol"])
    result["event_at"] = _times(result["event_at"], "event_at")
    result["available_at"] = _times(result["available_at"], "available_at")
    result["event_type"] = result["event_type"].astype("string").str.strip()
    result["source"] = _sources(result["source"])
    if (result["event_type"] == "").any():
        raise DataContractError("event types must be non-empty")
    result["payload"] = result["payload"].map(_payload)
    return result.sort_values(["available_at", "event_at", "symbol"], kind="stable").reset_index(
        drop=True
    )


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise DataContractError("event payload must be a JSON object")


def _normalize_universe(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty and not set(UNIVERSE_COLUMNS).issubset(frame.columns):
        return empty_universe()
    require_columns(frame, UNIVERSE_COLUMNS, DataKind.UNIVERSE)
    result = frame.copy()
    result["symbol"] = _symbols(result["symbol"])
    result["effective_from"] = _times(result["effective_from"], "effective_from")
    result["effective_to"] = _times(result["effective_to"], "effective_to", nullable=True)
    result["available_at"] = _times(result["available_at"], "available_at")
    result["source"] = _sources(result["source"])
    invalid = result["effective_to"].notna() & (result["effective_to"] <= result["effective_from"])
    if invalid.any():
        raise DataContractError("universe effective_to must be after effective_from")
    return result.sort_values(["effective_from", "symbol"], kind="stable").reset_index(drop=True)


@dataclass(frozen=True)
class DataBundle:
    """All stock data known to an evaluation, with availability timestamps."""

    prices: pd.DataFrame = field(default_factory=empty_prices)
    features: pd.DataFrame = field(default_factory=empty_features)
    events: pd.DataFrame = field(default_factory=empty_events)
    universe: pd.DataFrame = field(default_factory=empty_universe)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "prices", _normalize_prices(self.prices))
        object.__setattr__(self, "features", _normalize_features(self.features))
        object.__setattr__(self, "events", _normalize_events(self.events))
        object.__setattr__(self, "universe", _normalize_universe(self.universe))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def symbols(self) -> tuple[str, ...]:
        values: set[str] = set()
        for frame in (self.prices, self.features, self.events, self.universe):
            if "symbol" in frame:
                values.update(str(item) for item in frame["symbol"].dropna().unique())
        return tuple(sorted(values))

    @property
    def start(self) -> pd.Timestamp | None:
        return None if self.prices.empty else pd.Timestamp(self.prices["timestamp"].min())

    @property
    def end(self) -> pd.Timestamp | None:
        return None if self.prices.empty else pd.Timestamp(self.prices["timestamp"].max())

    def select(self, request: DataRequest) -> DataBundle:
        """Apply a request after loading, useful for simple file adapters."""
        prices = self.prices
        features = self.features
        events = self.events
        universe = self.universe
        if request.symbols:
            symbols = set(request.symbols)
            prices = prices[prices["symbol"].isin(symbols)]
            features = features[features["symbol"].isin(symbols)]
            events = events[events["symbol"].isin(symbols)]
            universe = universe[universe["symbol"].isin(symbols)]
        if request.start is not None:
            prices = prices[prices["timestamp"] >= request.start]
            features = features[features["observed_at"] >= request.start]
            events = events[events["event_at"] >= request.start]
        if request.end is not None:
            prices = prices[prices["timestamp"] <= request.end]
            features = features[features["observed_at"] <= request.end]
            events = events[events["event_at"] <= request.end]
        return DataBundle(
            prices=prices if DataKind.PRICES in request.kinds else empty_prices(),
            features=features if DataKind.FEATURES in request.kinds else empty_features(),
            events=events if DataKind.EVENTS in request.kinds else empty_events(),
            universe=universe if DataKind.UNIVERSE in request.kinds else empty_universe(),
            metadata=self.metadata,
        )

    def fingerprint(self) -> str:
        payload = {
            "prices": hash_dataframe(self.prices),
            "features": hash_dataframe(self.features),
            "events": hash_dataframe(self.events),
            "universe": hash_dataframe(self.universe),
            "metadata": self.metadata,
        }
        return sha256_text(canonical_json(payload))

    def with_prices(self, prices: pd.DataFrame) -> DataBundle:
        """Return a copy with replacement prices, used by causality tests."""
        return replace(self, prices=prices)

    def as_of(
        self, value: pd.Timestamp | str
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, tuple[str, ...]]:
        """Return only information that was available by the decision timestamp."""
        timestamp = _timestamp(value)
        prices = self.prices[self.prices["timestamp"] <= timestamp]
        features = self.features[
            (self.features["available_at"] <= timestamp)
            & (self.features["observed_at"] <= timestamp)
        ]
        events = self.events[self.events["available_at"] <= timestamp]
        if self.universe.empty:
            symbols = (
                tuple(
                    sorted(
                        prices.loc[
                            prices["timestamp"] == prices["timestamp"].max(), "symbol"
                        ].unique()
                    )
                )
                if not prices.empty
                else ()
            )
        else:
            active = self.universe[
                (self.universe["available_at"] <= timestamp)
                & (self.universe["effective_from"] <= timestamp)
                & (
                    self.universe["effective_to"].isna()
                    | (self.universe["effective_to"] > timestamp)
                )
            ]
            symbols = tuple(sorted(str(item) for item in active["symbol"].unique()))
        return prices, features, events, symbols

    def describe(self) -> dict[str, Any]:
        return {
            "symbols": len(self.symbols),
            "price_rows": len(self.prices),
            "feature_rows": len(self.features),
            "event_rows": len(self.events),
            "universe_rows": len(self.universe),
            "start": self.start,
            "end": self.end,
            "fingerprint": self.fingerprint(),
            "metadata": canonical_json(self.metadata),
        }
