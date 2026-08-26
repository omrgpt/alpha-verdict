# Quickstart: your first multimodal verdict in five minutes

This folder is a complete, runnable AlphaVerdict project. It bundles:

- `data/prices.csv` — 2.5 years of daily OHLCV for 8 fictional stocks + an index benchmark
- `data/fundamentals.csv` — quarterly gross-margin filings with realistic publication lags
- `data/events.csv` — post-earnings news sentiment as JSON payloads
- `data/universe.csv` — historical membership ledger
- `strategy.py` — a **multimodal strategy**: gross-margin quality (40%) +
  earnings sentiment (20%) + volatility-normalized momentum (40%)

## Run it

From this folder:

```bash
alphaverdict backtest
```

or, from the repo root without installing:

```bash
python -m alphaverdict backtest --config examples/quickstart/alphaverdict.yml
```

You get `runs/<run-id>/report.html`, `result.json`, `audit.json`, and
`manifest.json` — plus console output showing the verdict, what held up,
and the diagnosed next experiments for *this* strategy.

## What to look at

1. **The verdict and score.** Deterministic: rerun and you get the identical report.
2. **"What held up."** The council also reports what went RIGHT.
3. **"Diagnosed next experiments."** Each one cites numbers from your run and
   prescribes the exact re-run, plus how to read both outcomes. Try one: the
   advice is written to be executed by editing this config or strategy.
4. **Findings.** Stable machine-readable codes (`MULTIPLE_TESTING`,
   `SYMBOL_CONCENTRATION`, ...) linked to evidence.

## Then break it on purpose

Corrupt one fundamentals row so it claims to be knowable before it was
observed (move its `available_at` earlier than `observed_at`) and re-run.
The council fails the run with `DATA_TEMPORAL_LEAK`. That is the product:
a reviewer that catches the leak that would have silently inflated most
backtesting tools' results.

## Make it yours

- Point `data.adapter` options at your own CSV/Parquet exports (same four tables).
- Replace `strategy.py` with your own ranking logic; keep `score(snapshot)`.
- Or write a custom adapter for any provider/API you use — the data contract
  is four tables, documented in `docs/data-contract.md`.

Sample data is synthetic (seeded) and marked `synthetic_sample`; findings will
remind you that plumbing proofs are not market evidence.
