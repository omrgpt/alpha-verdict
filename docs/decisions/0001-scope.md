# ADR 0001: Stocks-only research without execution

- Status: accepted
- Date: 2026-08-20

## Context

The project could become a general algorithmic-trading platform, but that category
already contains mature engines and would force broker, order, market-calendar,
multi-asset, and deployment concerns into the trust boundary.

## Decision

AlphaVerdict supports daily stock screening and hypothetical portfolio backtesting.
It exposes no broker connection, order model, execution service, or live deployment.

## Consequences

The core stays smaller, safer, and easier to audit. Users needing live execution must
integrate a separate system after an independent decision process. Some users will
choose broader platforms; that is expected.
