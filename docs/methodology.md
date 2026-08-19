# Backtest methodology

AlphaVerdict’s engine is small enough to audit. It models a long-only,
cross-sectional stock portfolio at daily session resolution. It is not an exchange,
broker emulator, tax engine, or intraday fill simulator.

## Decision and execution timing

For each configured rebalance period:

1. choose the last available session as decision time (t);
2. construct `ResearchSnapshot(t)` from information available no later than (t);
3. rank the active point-in-time universe after the decision close;
4. execute selected weights at the next available session open (t+1);
5. hold until the following rebalance execution open;
6. subtract turnover-linked friction.

This prevents same-close execution of a signal that needs the completed close. A
strategy requiring a different timing model should not pretend this engine provides
it.

## Portfolio formation

Eligible scores are sorted descending with symbol as a deterministic tie-breaker.
The engine selects up to `top_k` names and supports:

- equal weighting;
- descending rank weighting;
- non-negative shifted score weighting.

Weights are normalized and capped by `max_weight`. Clipped or unavailable weight is
cash; it is not redistributed. Invalid entry/exit prices remove that name for the
period and leave its intended weight in cash.

## Turnover and costs

Before each rebalance, prior target weights are marked forward by realized
open-to-open returns. One-way turnover then compares the drifted portfolio with the
new target and includes implicit cash:

```text
0.5 × (Σ |new_stock_weight - old_stock_weight| + |new_cash - old_cash|)
```

Return drag is:

```text
turnover × (commission_bps + slippage_bps) / 10,000
```

This transparent approximation is suitable for coarse daily research, not a claim
about fills. Audit cost stresses rerun the entire backtest at configured multiples.

## Metrics

Results include compounded total and annual return, annualized volatility, Sharpe,
Sortino, Calmar, maximum drawdown, win rate, tails, turnover, exposure, and—when a
valid benchmark exists—beta, annualized alpha, information ratio, and correlation.
Undefined or non-finite ratios serialize as `null`, never infinity.

Annualization follows the rebalance frequency (252, 52, or 12 observations per
year). These are portfolio-period returns, not daily returns when weekly or monthly
rebalancing is selected.

## Statistical diagnostics

The default council applies:

- contiguous fold performance;
- circular block-bootstrap paths;
- a two-sided sign-randomization test of mean return;
- probabilistic Sharpe and minimum track-record approximations;
- an expected-maximum-Sharpe adjustment for the user-declared number of trials;
- return-period and stock-contribution concentration.

The multiple-testing logic is motivated by Bailey and López de Prado’s
[Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).
The broader need to account for strategy search is documented in Bailey et al.,
[The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253).
AlphaVerdict does **not** currently implement full combinatorially symmetric
cross-validation or claim a complete PBO estimate; its finding is a bounded warning
based on the declared search burden.

Historical-universe requirements respond to documented survival and look-ahead
distortions. For example, ter Horst, Nijman, and Verbeek study
[survivorship and attrition effects](https://doi.org/10.1016/S0304-405X(99)00040-9),
and Sornette et al. quantify
[look-ahead benchmark bias](https://arxiv.org/abs/0810.1922).

## Known limitations

- Daily bars cannot model intraday path, queue position, spread dynamics, halts, or
  market impact.
- A basis-point cost model cannot replace capacity analysis.
- Corporate actions are supplied and declared by the user’s adapter.
- Coarse benchmark regimes are diagnostics, not a regime model.
- Bootstrap and randomization assumptions can be wrong for a particular strategy.
- Honest `n_trials` cannot be inferred from the final code.
- No backtest—nor an audit pass—establishes future profitability.

These limitations belong in every interpretation, not in fine print after a result.
