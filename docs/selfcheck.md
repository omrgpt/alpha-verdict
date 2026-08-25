# Self-Check: the bias zoo

AlphaVerdict's council claims to catch look-ahead, survivorship spin, cost
fragility, and multiple-testing abuse. Self-Check holds that claim under
continuous test: a shipped corpus of deliberately broken datasets and
strategies — each encoding one classic research trap — that the council must
detect. If a future change makes any trap slip through, `alphaverdict
selfcheck` fails loudly instead of silently weakening the auditor.

## Run it

```bash
alphaverdict selfcheck
```

Exit code 0 means every planted trap was caught. The command is deterministic,
needs no network or model key, and finishes in seconds.

## The cases

| Case | Planted trap | Expected detection |
|---|---|---|
| `lookahead-metadata-smuggling` | Full-sample statistic smuggled through bundle metadata into strategy scores | `CAUSALITY_PREFIX_CHANGED` |
| `frozen-warmup-state` | Lazy global frozen on first screen, reused stale forever | `STRATEGY_STATEFUL_WARMUP` |
| `nondeterministic-strategy` | Unseeded randomness in scoring | `STRATEGY_NONDETERMINISTIC` |
| `impossible-prices` | high < low, negative closes | `DATA_PRICE_INVARIANT` |
| `feature-temporal-leak` | `available_at` before `observed_at` | `DATA_TEMPORAL_LEAK` |
| `survivorship-undisclosed` | No point-in-time membership proof | `DATA_SURVIVORSHIP_UNKNOWN` |
| `cost-fragile-turnover` | High-churn picks whose edge dies under friction | `COST_FRAGILE` / `FOLD_INSTABILITY` |
| `ledger-tampering-detected` | Edited trial-ledger entry | `TRIALS_LEDGER_TAMPERED` |
| `underdeclared-trials` | Three recorded variants vs `n_trials=1` | `TRIALS_UNDERDECLARED` |

## Why this matters

Backtesting tools are usually tested for *crash-freedom*, not for whether their
warnings actually fire. A reviewer that quietly stops detecting leaks is more
dangerous than one that crashes: users inherit false confidence. The zoo turns
every audit capability into a regression-tested contract.

## Extending the zoo

Add a case module function returning `(caught: bool, detail: str)`, register it
in `CASES`, and mirror it in `tests/test_selfcheck.py`. Every new finding code
should ship with a case that proves the code fires.
