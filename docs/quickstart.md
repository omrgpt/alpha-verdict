# Quickstart

## 1. Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
python -m pip install git+https://github.com/omrgpt/alpha-verdict.git
```

Python 3.11 or newer is required.

## 2. Run the synthetic proof

```bash
alphaverdict demo
```

This exercises prices, fundamental-like features, news-like events, historical
universe membership, screening, backtesting, every audit agent, and report
generation. Every output is marked synthetic and must not be treated as market
evidence.

## 3. Scaffold a real project

```bash
alphaverdict init my-research
cd my-research
```

Review `strategy.py` and `alphaverdict.yml`. Local strategies and adapters execute
Python, so never run an untrusted project without reviewing it.

## 4. Map your data

The built-in CSV adapter accepts any subset of optional feature/event/universe
tables, but daily prices are required. Each row must name its source. See the
[data contract](data-contract.md).

Do not commit licensed data or credentials. The scaffold ignores common local
artifacts, but repository hygiene remains your responsibility.

## 5. Validate, screen, and research

```bash
alphaverdict validate
alphaverdict screen --as-of 2026-08-19 --output runs/screen.json
alphaverdict backtest
```

`backtest` always runs the configured audit council and writes an immutable
run-ID directory. Begin with `audit.json`, not the equity curve.

## 6. Declare the search burden

Set `audit.n_trials` to the number of strategy variants you actually tried—not
only the number you kept. The statistical reviewer uses this declaration when
deflating confidence. Omitting failed experiments makes the audit less useful.
