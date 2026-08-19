<p align="center">
  <img src="docs/assets/alphaverdict-mark.svg" width="112" alt="AlphaVerdict mark">
</p>

<h1 align="center">AlphaVerdict</h1>

<p align="center"><strong>The point-in-time stock strategy research engine.</strong></p>

<p align="center">
  Bring your stock data and one ranking strategy. Get a daily screen, a causal
  backtest, and an adversarial verdict with evidence.
</p>

<p align="center">
  <a href="https://github.com/omrgpt/alpha-verdict/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/omrgpt/alpha-verdict/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://www.python.org/"><img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB.svg"></a>
  <a href="LICENSE"><img alt="Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-0b7285.svg"></a>
  <a href="https://github.com/omrgpt/alpha-verdict/security"><img alt="Security policy" src="https://img.shields.io/badge/security-policy-5eead4.svg"></a>
</p>

---

Most backtesting tools answer: **“What did this strategy return?”**

AlphaVerdict asks the harder question: **“What would have been knowable then, and
which reasons should stop me from believing this result?”**

It is deliberately narrow:

- stocks only;
- daily cross-sectional screening and portfolio research;
- user-owned or properly licensed data;
- no broker connections, order objects, live trading, or hosted service;
- deterministic evidence first, optional AI narrative last.

That boundary is the product. AlphaVerdict is built for independent researchers,
students, developers, and small teams who need institutional research discipline
without inheriting an execution platform.

> [!CAUTION]
> AlphaVerdict is research software—not investment advice, a recommendation, or a
> promise of future returns. A `PASS` verdict means only that a run survived the
> configured tests.

## One command to see the whole system

```bash
git clone https://github.com/omrgpt/alpha-verdict.git
cd alpha-verdict
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install -e .
alphaverdict demo
```

The demo generates **clearly labelled synthetic data**, runs the same strategy
through screening and causal backtesting, convenes five deterministic reviewers,
and writes:

```text
demo-runs/<run-id>/
├── report.html      # self-contained human review
├── result.json      # returns, holdings, signals, metrics
├── audit.json       # findings, evidence, recommendations
└── manifest.json    # hashes and reproducibility identity
```

Synthetic results prove plumbing, not an edge. AlphaVerdict says so in the report.

## Bring your own research

Create a portable project:

```bash
python -m pip install git+https://github.com/omrgpt/alpha-verdict.git
alphaverdict init my-research
cd my-research
```

The scaffold contains one strategy, one strict YAML file, and canonical data
contracts. Add data you are allowed to use, then:

Leave `request.symbols` empty to screen the full point-in-time universe, or list a
watchlist to constrain both screening and research. AlphaVerdict is exchange- and
region-neutral within one user-supplied daily session calendar per run.

```bash
alphaverdict validate
alphaverdict screen --as-of 2026-08-19 --output runs/screen.json
alphaverdict backtest
```

Your strategy is a normal Python class:

```python
import pandas as pd

from alphaverdict import ResearchSnapshot, StockStrategy
from alphaverdict.data.technicals import momentum


class Strategy(StockStrategy):
    name = "twelve-month-strength"
    minimum_history = 253

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        prices = snapshot.price_history(sessions=253)
        scores = momentum(prices, lookback=252)
        return scores.rename("score").rename_axis("symbol").reset_index()
```

The same contract drives the current-day screen and every historical decision.
No separate “backtest version” of the logic is allowed to drift.

## The point-in-time data contract

AlphaVerdict does not choose, download, or redistribute a provider. Adapters map
your real stock data into four canonical tables:

| Table | Required temporal meaning |
|---|---|
| `prices` | daily OHLCV at `timestamp` |
| `features` | fundamentals/estimates/alternative features with both `observed_at` and `available_at` |
| `events` | news, filings, or events with `event_at` and `available_at` |
| `universe` | historical membership with effective dates and the date membership became knowable |

The distinction is crucial. A quarter can end on March 31 while its filing becomes
public in May. Strategies see the feature in May—not in March. Revisions remain
separate rows. Historical universe membership prevents today’s survivors from
silently replacing yesterday’s opportunity set.

See the complete [data contract](docs/data-contract.md) and [adapter guide](docs/adapters.md).

## What the audit council attacks

Every default reviewer is deterministic, read-only, and independently testable:

| Reviewer | Questions it tries to falsify |
|---|---|
| Data integrity | Are OHLC rows impossible? Are adjustment and survivorship policies unproven? Is this synthetic? |
| Causality | Do repeated runs change? Do past signals change when future rows are corrupted? |
| Performance | Is the result too small, too extreme, too concentrated, or too close to friction? |
| Robustness | Does it fail across contiguous folds, cost multiples, bootstrap paths, or coarse regimes? |
| Statistics | Does it survive track-record length, sign randomization, return concentration, and the declared search burden? |

Findings are stable codes, not prose vibes. Recommendations are linked to evidence.
An optional model may summarize the final audit JSON, but it cannot see raw prices,
news payloads, strategy source, credentials, or filesystem paths—and it never enters
the ranking loop.

Read [methodology](docs/methodology.md) and [the audit council](docs/audit-council.md).

## Why AlphaVerdict exists

Excellent projects already own important categories:

- [vectorbt](https://github.com/polakowo/vectorbt) excels at fast, vectorized parameter exploration.
- [backtesting.py](https://github.com/kernc/backtesting.py) offers a concise OHLC strategy API and interactive results.
- [Backtrader](https://github.com/mementum/backtrader) provides a mature event-driven simulation and broker model.
- [Qlib](https://github.com/microsoft/qlib) spans AI-oriented quant research through production workflows.
- [LEAN](https://github.com/QuantConnect/Lean) is a professional, multi-asset backtesting and live-trading engine.

AlphaVerdict does not try to out-broker, out-chart, or out-optimize them. Its wedge is
the missing connective tissue between **multimodal point-in-time stock evidence** and
an **automated adversarial research verdict**, in a dependency-light package that
remains provider-neutral and local-first.

| Capability | AlphaVerdict | Typical backtest engine |
|---|:---:|:---:|
| One strategy contract for today’s screen and historical research | ✓ | varies |
| Fundamentals/news with explicit knowledge timestamps | first-class | often custom |
| Historical universe membership contract | first-class | varies |
| Future-perturbation causality test | built in | uncommon |
| Multi-agent deterministic audit with finding codes | built in | uncommon |
| User chooses every data provider | ✓ | varies |
| Broker or live-order surface | **intentionally absent** | often present |

The detailed, evidence-linked assessment is in
[competitive positioning](docs/competitive-positioning.md). Claims are scoped to
documented public capabilities, not “better than everything” marketing.

## Architecture

```text
Your adapter(s) ──► bitemporal DataBundle ──► ResearchSnapshot(as_of)
                                                    │
Your strategy.py ──────────────────────────────────►│ score stocks
                                                    ▼
                                      daily screen + causal backtest
                                                    │
                    ┌──────────┬──────────┬──────────┼──────────┐
                    ▼          ▼          ▼          ▼          ▼
                  data      causality  performance robustness statistics
                    └──────────┴──────────┴──────────┼──────────┘
                                                    ▼
                                 verdict + evidence + next tests
```

Core execution is deterministic. The current backtester is intentionally
conservative and auditable: signals form after a decision close, execute at the
next available open, hold to the next rebalance open, account for implicit cash,
and subtract turnover-linked commission and slippage.

## Security posture

Running a strategy or adapter executes trusted local Python. Treat configuration
from an unknown repository as code. AlphaVerdict narrows the surrounding blast
radius:

- YAML uses safe parsing and rejects unknown keys;
- file adapters and strategy paths are confined to the project root by default;
- remote URLs are rejected by the local-file adapter;
- secrets, datasets, artifacts, and local databases are ignored by default;
- reports contain hashes, not source code or credentials;
- no telemetry, network downloader, broker API, or hidden model call exists;
- CI includes static analysis, CodeQL, dependency review, package builds, and a
  90% coverage gate.

Read [SECURITY.md](SECURITY.md) before writing an adapter and see the full
[threat model](docs/security.md).

## Project status

AlphaVerdict is `0.1.0` alpha software. The data contract and finding codes aim to
be stable, but breaking changes may occur before `1.0`. The roadmap prioritizes
research validity over feature count: walk-forward model hooks, richer universe
audits, adapter conformance kits, report comparisons, and externally reproduced
reference cases.

We will not add broker keys, automatic execution, unverifiable “AI picks,” bundled
proprietary data, or performance promises. Those exclusions protect the project’s
identity.

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md), the
[governance model](GOVERNANCE.md), and [ROADMAP.md](ROADMAP.md). Good first
contributions include new invariant tests, adapter conformance fixtures, statistical
reviewers with primary-source methodology, and clearer explanations of failure.

```bash
python -m pip install -e ".[dev,docs,parquet]"
ruff format --check src tests examples
ruff check src tests examples
mypy src/alphaverdict
pytest
mkdocs build --strict
python -m build
```

Apache-2.0 licensed. See [NOTICE](NOTICE) and [DISCLAIMER.md](DISCLAIMER.md).
