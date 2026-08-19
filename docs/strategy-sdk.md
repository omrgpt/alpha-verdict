# Strategy SDK

A strategy is a trusted local Python object that inherits `StockStrategy` and
implements one method:

```python
def score(self, snapshot: ResearchSnapshot) -> object:
    ...
```

The output may be a symbol-indexed `Series`, a `{symbol: score}` mapping, a
`DataFrame`, or a `SignalSet`. Data frames support four columns:

| Column | Required | Meaning |
|---|:---:|---|
| `symbol` | yes | stock identifier |
| `score` | yes | finite numeric score; higher ranks first |
| `eligible` | no | defaults to `True` |
| `rationale` | no | bounded explanation, maximum 1,000 characters |

Duplicate symbols, empty identifiers, and non-finite scores for eligible rows are
contract failures. Stocks outside the point-in-time universe or below
`minimum_history` are made ineligible centrally.

## Multimodal example

```python
import pandas as pd

from alphaverdict import ResearchSnapshot, StockStrategy
from alphaverdict.data.technicals import cross_sectional_rank, momentum


class Strategy(StockStrategy):
    name = "quality-strength"
    minimum_history = 253

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        strength = momentum(snapshot.price_history(sessions=253), lookback=252)
        quality = snapshot.latest_features(["return_on_equity"])["return_on_equity"]

        frame = pd.DataFrame(index=pd.Index(snapshot.universe, name="symbol"))
        frame["strength"] = cross_sectional_rank(strength)
        frame["quality"] = cross_sectional_rank(quality)
        frame["score"] = 0.6 * frame["strength"] + 0.4 * frame["quality"]
        frame["eligible"] = frame[["strength", "quality"]].notna().all(axis=1)
        frame["rationale"] = "pre-declared strength and quality composite"
        return frame.reset_index()
```

The complete educational example in
[`examples/strategies/multimodal.py`](https://github.com/omrgpt/alpha-verdict/blob/main/examples/strategies/multimodal.py) also
uses point-in-time news events. It is an API example, not a recommended strategy.

## Snapshot API

- `price_history(symbols=None, sessions=None)` returns canonical rows no later than
  the snapshot.
- `latest_prices()` returns the last known row per active symbol.
- `latest_features(names=None)` returns the latest available revision pivoted by
  symbol.
- `feature_history(symbol, feature)` preserves every known revision.
- `known_events(event_type=None, symbols=None, include_future=False)` returns events
  already available at the snapshot.
- `history_counts()` counts known price sessions per symbol.

Returned frames are copies. Mutating them does not mutate the source bundle.

## Determinism contract

`clone()` uses deep copy by default. The causality reviewer evaluates independent
clones on identical snapshots and then corrupts every row after selected cutoffs.
Past signals must remain byte-for-byte equal.

If a strategy uses randomness, seed it from an explicit public parameter. Do not
read wall-clock time, global mutable state, a remote endpoint, or the full data file
inside `score()`. The snapshot is the evidence boundary.

## Trusted-code boundary

`strategy.py:Strategy` and installed `module:object` references execute Python.
AlphaVerdict prevents accidental path escape by default, but it is not a sandbox.
Review code before running it. A future sandbox would complement—not replace—the
need to trust financial research logic.
