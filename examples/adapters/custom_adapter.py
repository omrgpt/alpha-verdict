"""Example user-owned SQLite adapter; copy and review before use."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from alphaverdict.data import AdapterHealth, DataBundle, DataRequest
from alphaverdict.data.adapter import HealthStatus
from alphaverdict.exceptions import ConfigurationError
from alphaverdict.utils import resolve_within


class SQLiteAdapter:
    """Read four canonical tables from a local user-owned SQLite database."""

    name = "example-sqlite"

    def __init__(
        self,
        *,
        database: str,
        root: str | Path = ".",
        allow_outside_root: bool = False,
    ) -> None:
        self.path = resolve_within(
            Path(root),
            database,
            allow_outside=allow_outside_root,
        )

    def health(self) -> AdapterHealth:
        if not self.path.is_file():
            return AdapterHealth(self.name, HealthStatus.FAIL, "database file is missing")
        return AdapterHealth(self.name, HealthStatus.PASS, "database file is present")

    def load(self, request: DataRequest) -> DataBundle:
        if self.health().status is HealthStatus.FAIL:
            raise ConfigurationError("configured SQLite database is unavailable")
        with sqlite3.connect(self.path) as connection:
            frames = {
                table: pd.read_sql_query(f"SELECT * FROM {table}", connection)  # noqa: S608
                for table in ("prices", "features", "events", "universe")
            }
        return DataBundle(
            prices=frames["prices"],
            features=frames["features"],
            events=frames["events"],
            universe=frames["universe"],
            metadata={
                "adapter": self.name,
                "price_adjustment": "declare-me",
                "survivorship": "declare-me",
            },
        ).select(request)
