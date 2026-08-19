# Architecture

AlphaVerdict uses a ports-and-contracts design so provider code, research logic,
simulation, audit, and presentation can change independently.

```text
┌──────────────────────────────────────────────────────────────────┐
│ trusted user project                                             │
│ adapter plugin        strategy plugin        strict YAML         │
└──────────┬──────────────────┬────────────────────┬───────────────┘
           ▼                  │                    │
   canonical DataBundle      │                    │
   prices/features/events/   │                    │
   historical universe      │                    │
           │                 │                    │
           ▼                 ▼                    ▼
   ResearchSnapshot ───► normalized SignalSet ─► engine
                                                 │
                      ┌──────────────────────────┴───────────────┐
                      ▼                                          ▼
                 ScreenResult                              BacktestResult
                                                                 │
                         five read-only audit agents ◄────────────┘
                                      │
                                      ▼
                                 AuditReport
                                      │
                                      ▼
                           JSON + HTML + manifest
```

## Module boundaries

- `data`: canonical schemas, bitemporal filtering, adapters, fingerprints, and
  causal technical features.
- `strategy`: the author contract, normalized signals, snapshots, and explicit
  trusted-code loading.
- `engine`: schedules, open-to-open simulation, costs, metrics, and screening.
- `agents`: independent reviewers and deterministic council orchestration.
- `audit`: stable findings, verdicts, statistics, and recommendations.
- `config`: strict versioned project parsing and runtime construction.
- `report`: machine-readable evidence and self-contained HTML.

The core has no database, web framework, model SDK, broker SDK, or provider SDK.
The required runtime is NumPy, Pandas, PyYAML, Jinja2, Rich, and Typer.

## Design rules

1. A temporal field must state whether it means event time or knowledge time.
2. Strategies never receive the full bundle.
3. The same strategy contract powers screening and history.
4. Invalid data fails early; suspicious but possible data becomes an audit finding.
5. Auditors are read-only and return bounded schemas.
6. Reports cannot affect results.
7. Optional AI is downstream of the deterministic verdict.
8. No core type represents an order or broker account.

Architecture decisions are recorded in [`docs/decisions`](decisions/0001-scope.md).
