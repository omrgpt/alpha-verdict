# Data adapters

Adapters let users keep provider choice, credentials, licensing, caching, and symbol
mapping outside AlphaVerdict. The core protocol is intentionally small:

```python
class DataAdapter(Protocol):
    name: str

    def health(self) -> AdapterHealth: ...
    def load(self, request: DataRequest) -> DataBundle: ...
```

`health()` should be side-effect free. `load()` receives bounded dates, symbols,
and requested table kinds.

## Built-in local files

```yaml
data:
  adapter: csv
  options:
    prices: data/prices.csv
    features: data/features.parquet
    events: data/events.csv
    universe: data/universe.csv
    metadata:
      price_adjustment: split_adjusted
      survivorship: point_in_time
```

CSV and Parquet are supported. Event payloads inside CSV must be JSON objects encoded
as strings. The adapter accepts local paths only and confines them to the project
root unless `allow_outside_root: true` is explicitly set.

## A private provider adapter

Keep provider imports and credentials in your own package:

```python
from alphaverdict.data import AdapterHealth, DataBundle, DataRequest
from alphaverdict.data.adapter import HealthStatus


class WarehouseAdapter:
    name = "company-warehouse"

    def health(self) -> AdapterHealth:
        return AdapterHealth(self.name, HealthStatus.PASS, "configuration present")

    def load(self, request: DataRequest) -> DataBundle:
        prices = query_prices(request.start, request.end, request.symbols)
        features = query_features_as_known_then(request)
        events = query_events_as_known_then(request)
        universe = query_historical_membership(request)
        return DataBundle(prices, features, events, universe, metadata={...})
```

Reference it explicitly:

```yaml
data:
  adapter: my_research.adapters:WarehouseAdapter
  options: {}
```

Or publish a Python entry point under `alphaverdict.data_adapters`. The complete
minimal shape is in
[`examples/adapters/custom_adapter.py`](https://github.com/omrgpt/alpha-verdict/blob/main/examples/adapters/custom_adapter.py).

## Credential rules

- Read secrets from the environment or an operating-system secret manager.
- Never place tokens in YAML, metadata, source strings, logs, or reports.
- Return source identifiers, not credential-bearing URLs.
- Bound retries and timeouts in remote adapters.
- Cache only where the user has rights to do so.
- Make redistribution and retention requirements visible in adapter documentation.

AlphaVerdict itself makes no network request during a normal CSV run or synthetic
demo.
