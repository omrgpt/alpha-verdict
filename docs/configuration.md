# Configuration reference

Project files are YAML with `version: 1`. Parsing uses `yaml.safe_load`; unknown keys
are rejected so misspelled assumptions cannot fail silently.

```yaml
version: 1

data:
  adapter: csv
  options:
    prices: data/prices.csv

strategy: strategy.py:Strategy

request:
  start: 2015-01-01
  end: 2025-12-31
  symbols: []
  kinds: [prices, features, events, universe]

screen:
  top_n: 20
  minimum_score:

backtest:
  start:
  end:
  rebalance: weekly       # daily | weekly | monthly
  top_k: 10
  minimum_score:
  weighting: equal       # equal | rank | score
  max_weight: 0.20
  commission_bps: 5
  slippage_bps: 10
  benchmark_symbol:
  initial_capital: 100000
  annual_risk_free_rate: 0
  seed: 7

audit:
  n_trials: 1
  bootstrap_simulations: 500
  bootstrap_block_size: 5
  permutation_simulations: 500
  confidence: 0.95
  cost_multipliers: [0, 1, 2, 5]
  causality_cutoffs: 3
  stability_folds: 4
  minimum_periods: 24
  seed: 7

output_dir: runs
allow_outside_root: false
```

## Important distinctions

`request.start/end` limit data loaded by an adapter. `backtest.start/end` limit the
evaluation schedule. Load enough history before the first backtest decision to
satisfy strategy warm-up.

An empty `request.symbols` uses the adapter’s supplied universe. A non-empty list is
an optional watchlist applied consistently to every canonical table.

`maximum_weight` is a cap, not a target. AlphaVerdict does not redistribute clipped
weight, so residual exposure remains cash. Likewise, a selected stock missing a
valid execution price remains cash.

`n_trials` is the complete number of variants tried in the research process. This
cannot be inferred from the winning strategy file, so honest user input is required.

`allow_outside_root` weakens a safety boundary and should remain false. It does not
sandbox trusted Python plugins.
