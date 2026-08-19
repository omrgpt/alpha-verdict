"""Generate a minimal, reviewable bring-your-own-data project."""

from __future__ import annotations

from pathlib import Path

from alphaverdict.exceptions import ConfigurationError

CONFIG = """version: 1

data:
  adapter: csv
  options:
    prices: data/prices.csv
    features: data/features.csv
    events: data/events.csv
    universe: data/universe.csv
    metadata:
      price_adjustment: unknown
      survivorship: unknown

strategy: strategy.py:Strategy

request:
  kinds: [prices, features, events, universe]
  symbols: []

screen:
  top_n: 20

backtest:
  rebalance: weekly
  top_k: 10
  weighting: equal
  max_weight: 0.20
  commission_bps: 5
  slippage_bps: 10
  benchmark_symbol:
  seed: 7

audit:
  n_trials: 1
  bootstrap_simulations: 500
  permutation_simulations: 500
  confidence: 0.95
  seed: 7

output_dir: runs
allow_outside_root: false
"""

STRATEGY = '''"""Your trusted local stock-ranking strategy."""

import pandas as pd

from alphaverdict import ResearchSnapshot, StockStrategy
from alphaverdict.data.technicals import momentum


class Strategy(StockStrategy):
    name = "my-stock-strategy"
    minimum_history = 126

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        prices = snapshot.price_history(sessions=127)
        scores = momentum(prices, lookback=126)
        return scores.rename("score").rename_axis("symbol").reset_index()
'''

DATA_README = """# Bring your own stock data

AlphaVerdict never downloads or redistributes market data. Put user-owned or
properly licensed canonical tables here, or configure your own adapter.

Required price columns:
`symbol,timestamp,open,high,low,close,volume,source`

Feature columns:
`symbol,observed_at,available_at,feature,value,source,revision`

Event columns:
`symbol,event_at,available_at,event_type,payload,source`

Universe columns:
`symbol,effective_from,effective_to,available_at,source`

Do not commit datasets, provider credentials, or API keys.
"""

GITIGNORE = """.env
*.key
*.pem
data/*.csv
data/*.parquet
runs/
.venv/
__pycache__/
"""


def initialize_project(destination: Path, *, force: bool = False) -> tuple[Path, ...]:
    """Create a project without overwriting files unless explicitly requested."""
    root = destination.expanduser().resolve()
    files = {
        root / "alphaverdict.yml": CONFIG,
        root / "strategy.py": STRATEGY,
        root / "data" / "README.md": DATA_README,
        root / ".gitignore": GITIGNORE,
    }
    conflicts = [path for path in files if path.exists() and not force]
    if conflicts:
        names = ", ".join(str(path.relative_to(root)) for path in conflicts)
        raise ConfigurationError(f"refusing to overwrite existing files: {names}")
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tuple(files)
