"""Built-in adapter for user-owned CSV or Parquet datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from alphaverdict.data.adapter import AdapterHealth, HealthStatus
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataRequest, empty_events, empty_features, empty_universe
from alphaverdict.exceptions import ConfigurationError
from alphaverdict.utils import resolve_within


class CSVBundleAdapter:
    """Load canonical tables from local files without owning provider credentials."""

    name = "csv"

    def __init__(
        self,
        *,
        prices: str,
        features: str | None = None,
        events: str | None = None,
        universe: str | None = None,
        root: str | Path = ".",
        allow_outside_root: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.allow_outside_root = allow_outside_root
        self.paths = {
            "prices": resolve_within(self.root, prices, allow_outside=allow_outside_root),
            "features": self._optional(features),
            "events": self._optional(events),
            "universe": self._optional(universe),
        }
        self.metadata = {
            "adapter": self.name,
            "data_classification": "user_supplied",
            **(metadata or {}),
        }

    def _optional(self, value: str | None) -> Path | None:
        return (
            None
            if value is None
            else resolve_within(self.root, value, allow_outside=self.allow_outside_root)
        )

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".parquet", ".pq"}:
            try:
                return pd.read_parquet(path)
            except ImportError as exc:
                raise ConfigurationError(
                    "install alphaverdict[parquet] to read Parquet files"
                ) from exc
        raise ConfigurationError(f"unsupported data file type: {path.suffix or '<none>'}")

    def health(self) -> AdapterHealth:
        missing = [
            name for name, path in self.paths.items() if path is not None and not path.is_file()
        ]
        if missing:
            return AdapterHealth(
                self.name, HealthStatus.FAIL, f"missing files: {', '.join(missing)}"
            )
        return AdapterHealth(
            self.name, HealthStatus.PASS, "all configured local files are readable candidates"
        )

    def load(self, request: DataRequest) -> DataBundle:
        health = self.health()
        if health.status is HealthStatus.FAIL:
            raise ConfigurationError(health.detail)
        price_path = self.paths["prices"]
        if price_path is None:
            raise ConfigurationError("a prices file is required")
        bundle = DataBundle(
            prices=self._read(price_path),
            features=self._read(self.paths["features"])
            if self.paths["features"]
            else empty_features(),
            events=self._read(self.paths["events"]) if self.paths["events"] else empty_events(),
            universe=self._read(self.paths["universe"])
            if self.paths["universe"]
            else empty_universe(),
            metadata=self.metadata,
        )
        return bundle.select(request)
