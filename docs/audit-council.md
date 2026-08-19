# Audit council

The council is a deterministic swarm: independent reviewers inspect the same
immutable context concurrently, then a stable merge orders findings by severity,
code, and agent. Concurrency changes latency, not results.

## Finding schema

Every finding contains:

```text
code, severity, title, evidence, recommendation, agent, metrics
```

Severities have fixed score penalties: critical 35, high 15, medium 7, low 2,
informational 0. Any critical finding forces `FAIL`; high findings or a score below
75 produce `WARN`; a score below 40 also forces `FAIL`.

The score is triage, not a probability and not an investment rating.

## Default finding codes

| Area | Codes |
|---|---|
| Data | `DATA_PRICE_INVARIANT`, `DATA_TEMPORAL_LEAK`, `DATA_ADJUSTMENT_UNKNOWN`, `DATA_SURVIVORSHIP_UNKNOWN`, `DATA_COVERAGE_UNEVEN`, `DATA_SYNTHETIC` |
| Causality | `STRATEGY_NONDETERMINISTIC`, `CAUSALITY_PREFIX_CHANGED`, `CAUSALITY_UNTESTED` |
| Robustness | `FOLD_INSTABILITY`, `BOOTSTRAP_UNCERTAIN`, `COST_FRAGILE`, `BENCHMARK_MISSING`, `REGIME_INSTABILITY` |
| Performance | `PERFORMANCE_SAMPLE_SMALL`, `PERFORMANCE_EXTREME_SHARPE`, `SYMBOL_CONCENTRATION`, `BENCHMARK_UNDERPERFORMANCE` |
| Statistics | `TRACK_RECORD_SHORT`, `MULTIPLE_TESTING`, `MEAN_NOT_SIGNIFICANT`, `RETURN_CONCENTRATION` |

Codes are intended for CI policies and report comparisons. New codes require tests,
clear evidence semantics, an actionable recommendation, and a changelog entry.

## Prefix-invariance test

At several historical cutoffs, the causality reviewer:

1. evaluates two isolated strategy clones on the same snapshot;
2. corrupts every future price, feature, and event row;
3. rebuilds the same cutoff snapshot;
4. requires exact equality of normalized signals.

This catches a class of full-sample transforms, future backfills, and hidden global
state. It cannot prove all possible code is causal; it is one adversarial invariant.

## Evidence-backed recommendations

The council recommends research changes, not strategy “improvements.” Examples:

- correct availability timestamps;
- provide historical membership and delistings;
- reduce turnover or increase friction assumptions;
- preserve a fresh holdout;
- record all attempted variants;
- inspect dependence on dominant symbols or periods.

It never mutates a strategy, tunes parameters, or promotes a stock.

## Optional narrative model

`BoundedNarrativeReviewer` accepts a user-supplied text callable. It receives only
the merged audit JSON and an instruction forbidding new facts, predictions, targets,
or trade instructions. Output is length-bounded. This extension is off by default
and has no role in screening, backtesting, scoring, or verdict computation.
