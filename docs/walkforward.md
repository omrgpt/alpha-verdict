# Walk-forward evaluation

Single-sample backtests answer one question. Walk-forward analysis answers the
harder one: **does the edge persist on untouched, later data?**

`alphaverdict walkforward` splits the decision timeline into contiguous,
non-overlapping folds separated by an embargo gap, evaluates in-sample (IS) and
out-of-sample (OOS) windows separately, and reports degradation evidence with a
deterministic verdict hint.

## Run it

```bash
alphaverdict walkforward --config alphaverdict.yml \
  --train 52 --test 13 --embargo 2
```

All durations are counted in rebalance periods, matching `backtest.rebalance`, so
a weekly backtest counts weeks. The command writes `runs/walkforward.json`
alongside the standard artifacts.

## Output schema

```json
{
  "strategy": "twelve-month-strength",
  "config": {"train_periods": 52, "test_periods": 13, "embargo_periods": 2},
  "verdict_hint": "consistent",
  "mean_train_sharpe": 0.147,
  "pooled_oos_sharpe": 0.088,
  "degradation_ratio": 0.60,
  "folds": [
    {
      "index": 0,
      "train_start": "...", "train_end": "...",
      "test_start": "...",  "test_end": "...",
      "train_total_return": 0.051, "test_total_return": 0.012,
      "train_sharpe": 0.135, "test_sharpe": 0.098,
      "test_max_drawdown": -0.044
    }
  ],
  "warnings": ["..."]
}
```

## Interpretation

| Signal | Meaning |
| --- | --- |
| `degradation_ratio >= 0.7` | OOS retains most of the IS Sharpe; consistent behaviour. |
| `degradation_ratio < 0.5` | Hint `degraded`: the edge mostly lived in the past. |
| Any fold `test_total_return <= 0` | Hint `fragile`: persistence is uneven across regimes. |
| Fewer than two complete folds | Hard error: extend the history; no claim is possible. |

## Why the embargo matters

With overlapping holding periods, labels just before a split share information
with labels just after it (López de Prado's purged/embargoed cross-validation).
The embargo gap removes that channel: training decisions end at least
`embargo_periods` before the first test decision, so no training evaluation can
see a price path that overlaps the test window.

## Determinism

Folds are derived from the session calendar and configuration only — never
randomly. Two runs on identical inputs produce byte-identical JSON.
