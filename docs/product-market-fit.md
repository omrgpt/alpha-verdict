# Product-market fit thesis

Product-market fit is a hypothesis to validate, not a line of code or a star target.
AlphaVerdict’s initial wedge is intentionally narrow enough to test.

## Primary user

An independent stock researcher, student, developer, or small quantitative team who:

- can express a stock-ranking idea in Python;
- has access to real data but does not want provider lock-in;
- needs a daily shortlist and a defensible historical evaluation;
- cares about leakage, survivorship, friction, and overfitting;
- does not need AlphaVerdict to place trades.

The job is: **“Turn my heterogeneous stock evidence into a repeatable daily ranking,
then tell me why I should not trust its backtest.”**

## Pain being removed

Today this user often hand-builds the glue between prices, fundamentals, news,
historical constituents, a screener, a backtester, statistical notebooks, and report
files. The result is difficult to reproduce and easiest to inspect exactly where
the researcher is most biased toward believing it.

AlphaVerdict standardizes that glue while leaving the strategy and provider under
the user’s control.

## Why the wedge can compound

The defensible advantage is not one indicator or backtest loop. It is the composed
contract:

1. bitemporal multimodal stock evidence;
2. one strategy interface for present and history;
3. adversarial invariants with stable finding codes;
4. reproducible, hash-bound evidence artifacts;
5. an adapter ecosystem that does not require core provider ownership.

Each contributed adapter conformance case, seeded-bias fixture, reviewer, and public
reproduction corpus makes the system more useful and harder to recreate as a thin
wrapper. Apache-2.0 and a dependency-light core lower adoption friction for both
individuals and companies.

## Anti-personas

AlphaVerdict is not initially for high-frequency execution, options/futures/crypto,
broker automation, drag-and-drop users, hosted collaborative notebooks, or anyone
seeking guaranteed picks. Serving those groups now would erase the wedge.

## Validation metrics

Stars are a distribution signal, not proof of value. The first product metrics are:

- **activation:** a new user reaches the synthetic verdict in under five minutes;
- **time to own data:** a technical user produces a first canonical screen in under
  thirty minutes with the CSV path;
- **research retention:** projects rerun on new daily data over four consecutive weeks;
- **defect value:** seeded leakage, survivorship, and friction failures are caught in
  public conformance fixtures;
- **ecosystem pull:** external adapters and audit agents are maintained outside core;
- **trust:** independent users reproduce the same run ID from the same fixture;
- **clarity:** issue reports distinguish data, strategy, engine, and audit failures.

The maintainer should interview early users and publish aggregate, non-sensitive
activation evidence before declaring product-market fit.

## Distribution loop

Useful reports are portable and explain failures clearly, making them natural to
share in research reviews and education. Shared synthetic reproductions lead users
back to the contracts; new users contribute edge-case fixtures; those fixtures make
the auditors stronger; stronger auditors make future reports more trustworthy.

No growth loop should depend on exaggerated returns, copied proprietary data, or
financial fear of missing out.
