"""Read-only point-in-time view exposed to strategy code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import _timestamp


@dataclass(frozen=True)
class ResearchSnapshot:
    """All and only information knowable at one decision timestamp."""

    as_of: pd.Timestamp
    prices: pd.DataFrame
    features: pd.DataFrame
    events: pd.DataFrame
    universe: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def _cache(self) -> dict[str, Any]:
        cache = getattr(self, "_matrix_cache", None)
        if cache is None:
            cache = {}
            object.__setattr__(self, "_matrix_cache", cache)
        return cache

    def close_matrix(self) -> pd.DataFrame:
        """Cached date-by-symbol close pivot for this snapshot."""
        cache = self._cache()
        if "close_matrix" not in cache:
            cache["close_matrix"] = (
                self.prices.pivot(index="timestamp", columns="symbol", values="close")
                .sort_index()
                .copy()
            )
        matrix: pd.DataFrame = cache["close_matrix"]
        return matrix

    def open_matrix(self) -> pd.DataFrame:
        """Cached date-by-symbol open pivot for this snapshot."""
        cache = self._cache()
        if "open_matrix" not in cache:
            cache["open_matrix"] = (
                self.prices.pivot(index="timestamp", columns="symbol", values="open")
                .sort_index()
                .copy()
            )
        matrix: pd.DataFrame = cache["open_matrix"]
        return matrix

    def trailing_momentum(self, lookback: int) -> pd.Series:
        """Latest trailing total return per symbol from the cached close matrix."""
        if lookback < 1:
            raise ValueError("lookback must be positive")
        matrix = self.close_matrix()
        if len(matrix) <= lookback:
            return pd.Series(dtype=float)
        return matrix.iloc[-1] / matrix.iloc[-lookback - 1] - 1

    @classmethod
    def from_bundle(cls, bundle: DataBundle, as_of: pd.Timestamp | str) -> ResearchSnapshot:
        timestamp = _timestamp(as_of)
        prices, features, events, universe = bundle.as_of(timestamp)
        return cls(
            as_of=timestamp,
            prices=prices.copy(),
            features=features.copy(),
            events=events.copy(),
            universe=universe,
            metadata=dict(bundle.metadata),
        )

    def price_history(
        self,
        symbols: tuple[str, ...] | list[str] | None = None,
        *,
        sessions: int | None = None,
    ) -> pd.DataFrame:
        """Return canonical price rows up to this snapshot, optionally bounded."""
        result = self.prices
        if symbols is not None:
            normalized = {str(symbol).strip().upper() for symbol in symbols}
            result = result[result["symbol"].isin(normalized)]
        if sessions is not None:
            if sessions <= 0:
                raise ValueError("sessions must be positive")
            dates = result["timestamp"].drop_duplicates().sort_values().tail(sessions)
            result = result[result["timestamp"].isin(dates)]
        return result.copy()

    def latest_prices(self) -> pd.DataFrame:
        """Return the most recent known price row for each active symbol."""
        if self.prices.empty:
            return self.prices.copy()
        result = (
            self.prices.sort_values(["timestamp", "symbol"]).groupby("symbol", sort=False).tail(1)
        )
        if self.universe:
            result = result[result["symbol"].isin(self.universe)]
        return result.set_index("symbol", drop=False).sort_index()

    def latest_features(self, names: tuple[str, ...] | list[str] | None = None) -> pd.DataFrame:
        """Pivot the latest available revision of each feature by symbol."""
        frame = self.features
        if names is not None:
            frame = frame[frame["feature"].isin(set(names))]
        if self.universe:
            frame = frame[frame["symbol"].isin(self.universe)]
        if frame.empty:
            return pd.DataFrame(index=pd.Index(self.universe, name="symbol"))
        latest = (
            frame.sort_values(["observed_at", "available_at", "revision"], kind="stable")
            .groupby(["symbol", "feature"], sort=False)
            .tail(1)
        )
        result = latest.pivot(index="symbol", columns="feature", values="value")
        result.columns.name = None
        return result.sort_index()

    def feature_history(self, symbol: str, feature: str) -> pd.DataFrame:
        """Return every available revision for one feature."""
        normalized = symbol.strip().upper()
        result = self.features[
            (self.features["symbol"] == normalized) & (self.features["feature"] == feature)
        ]
        return result.sort_values(["observed_at", "available_at", "revision"]).copy()

    def known_events(
        self,
        *,
        event_type: str | None = None,
        symbols: tuple[str, ...] | list[str] | None = None,
        include_future: bool = False,
    ) -> pd.DataFrame:
        """Return events available now; future scheduled events are opt-in."""
        result = self.events
        if event_type is not None:
            result = result[result["event_type"] == event_type]
        if symbols is not None:
            normalized = {str(symbol).strip().upper() for symbol in symbols}
            result = result[result["symbol"].isin(normalized)]
        if not include_future:
            result = result[result["event_at"] <= self.as_of]
        return result.copy()

    def history_counts(self) -> pd.Series:
        """Count available price sessions for each symbol."""
        return self.prices.groupby("symbol")["timestamp"].nunique().astype(int)
