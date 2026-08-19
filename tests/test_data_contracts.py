"""Canonical data, adapter, and temporal-boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from alphaverdict.data.adapter import DataAdapter, HealthStatus
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataKind, DataRequest, empty_prices
from alphaverdict.data.csv import CSVBundleAdapter
from alphaverdict.data.registry import adapter_class, import_object
from alphaverdict.exceptions import ConfigurationError, DataContractError, SecurityBoundaryError
from alphaverdict.utils import (
    canonical_json,
    hash_dataframe,
    resolve_within,
    sha256_file,
    sha256_text,
)


def test_request_normalizes_symbols_and_dates() -> None:
    request = DataRequest(start="2024-01-01", end="2024-02-01", symbols=(" aapl ", "AAPL", "msft"))
    assert request.symbols == ("AAPL", "MSFT")
    assert request.start == pd.Timestamp("2024-01-01", tz="UTC")
    assert DataKind.PRICES in request.kinds
    with pytest.raises(DataContractError, match="after end"):
        DataRequest(start="2025-01-01", end="2024-01-01")
    with pytest.raises(DataContractError, match="invalid timestamp"):
        DataRequest(start="not-a-date")


def test_bundle_normalizes_and_slices_point_in_time(demo_bundle: DataBundle) -> None:
    assert demo_bundle.symbols[0] == "AURORA"
    cutoff = demo_bundle.prices["timestamp"].drop_duplicates().iloc[100]
    prices, features, events, symbols = demo_bundle.as_of(cutoff)
    assert prices["timestamp"].max() <= cutoff
    assert features.empty or features["available_at"].max() <= cutoff
    assert events.empty or events["available_at"].max() <= cutoff
    assert "DEMO-BENCH" in symbols
    selected = demo_bundle.select(
        DataRequest(
            start=cutoff,
            end=demo_bundle.end,
            symbols=("AURORA",),
            kinds=frozenset({DataKind.PRICES}),
        )
    )
    assert selected.symbols == ("AURORA",)
    assert selected.features.empty and selected.events.empty and selected.universe.empty


def test_bundle_rejects_bad_schemas_and_keys(tiny_bundle: DataBundle) -> None:
    duplicate = pd.concat([tiny_bundle.prices, tiny_bundle.prices.iloc[[0]]])
    with pytest.raises(DataContractError, match="duplicate"):
        DataBundle(prices=duplicate)
    with pytest.raises(DataContractError, match="missing columns"):
        DataBundle(prices=pd.DataFrame({"symbol": ["AAA"]}))
    bad_symbol = tiny_bundle.prices.copy()
    bad_symbol.loc[0, "symbol"] = ""
    with pytest.raises(DataContractError, match="symbols"):
        DataBundle(prices=bad_symbol)
    bad_number = tiny_bundle.prices.astype({"open": "object"}).copy()
    bad_number.loc[0, "open"] = "invalid"
    with pytest.raises(DataContractError, match="non-numeric"):
        DataBundle(prices=bad_number)


def test_feature_event_and_universe_contracts(tiny_bundle: DataBundle) -> None:
    date = tiny_bundle.end
    assert date is not None
    feature = pd.DataFrame(
        [
            {
                "symbol": "aaa",
                "observed_at": date,
                "available_at": date,
                "feature": "roe",
                "value": 0.2,
                "source": "x",
            }
        ]
    )
    event = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "event_at": date,
                "available_at": date,
                "event_type": "news",
                "payload": json.dumps({"sentiment": 1}),
                "source": "x",
            }
        ]
    )
    universe = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "effective_from": date,
                "effective_to": pd.NaT,
                "available_at": date,
                "source": "x",
            }
        ]
    )
    bundle = DataBundle(tiny_bundle.prices, feature, event, universe)
    assert bundle.features.iloc[0]["revision"] == 0
    assert bundle.events.iloc[0]["payload"] == {"sentiment": 1}
    bad_event = event.copy()
    bad_event.loc[0, "payload"] = "[]"
    with pytest.raises(DataContractError, match="JSON object"):
        DataBundle(events=bad_event)
    bad_universe = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "effective_from": date,
                "effective_to": date,
                "available_at": date,
                "source": "x",
            }
        ]
    )
    with pytest.raises(DataContractError, match="after effective_from"):
        DataBundle(universe=bad_universe)


def test_fingerprints_are_order_independent_and_sensitive(
    tiny_bundle: DataBundle, tmp_path: Path
) -> None:
    shuffled = tiny_bundle.prices.sample(frac=1, random_state=4)
    assert hash_dataframe(shuffled) == hash_dataframe(tiny_bundle.prices)
    assert (
        DataBundle(prices=shuffled, metadata={"fixture": True}).fingerprint()
        == tiny_bundle.fingerprint()
    )
    changed = tiny_bundle.prices.copy()
    changed.loc[0, "close"] += 1
    assert hash_dataframe(changed) != hash_dataframe(tiny_bundle.prices)
    target = tmp_path / "hash.txt"
    target.write_text("alpha", encoding="utf-8")
    assert sha256_file(target) == sha256_text("alpha")
    assert canonical_json({"bad": float("nan"), "path": target}).startswith('{"bad":null')


def test_path_boundary_blocks_escape_and_urls(tmp_path: Path) -> None:
    inside = resolve_within(tmp_path, "data/file.csv")
    assert inside == (tmp_path / "data" / "file.csv").resolve()
    with pytest.raises(SecurityBoundaryError, match="escapes"):
        resolve_within(tmp_path, "../outside.csv")
    with pytest.raises(SecurityBoundaryError, match="URLs"):
        resolve_within(tmp_path, "https://example.test/data.csv")
    outside = resolve_within(tmp_path, "../outside.csv", allow_outside=True)
    assert outside.name == "outside.csv"


def test_csv_adapter_loads_and_reports_health(tiny_bundle: DataBundle, tmp_path: Path) -> None:
    tiny_bundle.prices.to_csv(tmp_path / "prices.csv", index=False)
    adapter = CSVBundleAdapter(prices="prices.csv", root=tmp_path)
    assert isinstance(adapter, DataAdapter)
    assert adapter.health().status is HealthStatus.PASS
    loaded = adapter.load(DataRequest(symbols=("AAA",)))
    assert loaded.symbols == ("AAA",)
    missing = CSVBundleAdapter(prices="missing.csv", root=tmp_path)
    assert missing.health().status is HealthStatus.FAIL
    with pytest.raises(ConfigurationError, match="missing files"):
        missing.load(DataRequest())
    unknown = tmp_path / "prices.txt"
    unknown.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unsupported"):
        CSVBundleAdapter(prices="prices.txt", root=tmp_path).load(DataRequest())


def test_registry_resolves_explicit_and_entry_point_adapter() -> None:
    assert import_object("alphaverdict.data.csv:CSVBundleAdapter") is CSVBundleAdapter
    assert adapter_class("csv") is CSVBundleAdapter
    with pytest.raises(ConfigurationError, match="module:object"):
        import_object("invalid")
    with pytest.raises(ConfigurationError, match="not found"):
        import_object("alphaverdict.data.csv:Missing")
    with pytest.raises(ConfigurationError, match="unknown data adapter"):
        adapter_class("definitely-missing")
    with pytest.raises(ConfigurationError, match="must be a class"):
        adapter_class("alphaverdict.data.csv:pd")


def test_empty_bundle_and_describe() -> None:
    bundle = DataBundle(prices=empty_prices())
    assert bundle.start is None and bundle.end is None and bundle.symbols == ()
    assert bundle.as_of("2024-01-01")[3] == ()
    assert bundle.describe()["price_rows"] == 0
