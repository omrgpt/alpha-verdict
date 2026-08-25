# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project intends to
use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Trial ledger** (`alphaverdict ledger`): every backtest and demo run appends
  to an append-only, hash-chained `trials.jsonl` with a `.head` completeness
  checkpoint. A sixth council reviewer (TrialsAgent) reconciles the recorded
  variant count against the declared `audit.n_trials`, raising
  `TRIALS_LEDGER_MISSING` / `TRIALS_UNDERDECLARED` / `TRIALS_LEDGER_TAMPERED`
  so Deflated Sharpe reflects evidence, not self-report.
- **Self-Check bias zoo** (`alphaverdict selfcheck`): nine planted-trap cases —
  metadata look-ahead smuggling, frozen warmup state, nondeterminism, broken
  OHLC, temporal feature leaks, undisclosed survivorship, cost fragility,
  ledger tampering, understated search burden — that the council must catch or
  the command fails. The auditor now continuously tests itself.
- Causality reviewer gains a stale-warmup probe (`STRATEGY_STATEFUL_WARMUP`)
  detecting strategies whose output depends on evaluation order.
- Future-perturbation probe now also corrupts bundle metadata: metadata is not
  temporally governed, so strategies that derive scores from it are flagged as
  non-causal instead of slipping through.

### Fixed

- Report HTML autoescape was silently disabled because `select_autoescape`
  keys on the template's final extension (`.j2`); data-derived strings could
  reach `report.html` unescaped. Autoescape is now explicit and a regression
  test locks hostile strings out of reports.
- Strategies returning an empty column-less frame ("nothing eligible yet")
  no longer crash the strategy contract; they normalize to canonical columns.

### Planned

- External adapter conformance kit and independently reproduced reference fixtures.

## [0.3.0] - 2026-08-24

### Added

- Walk-forward evaluation engine with embargoed contiguous folds
  (`alphaverdict walkforward`), pooled out-of-sample metrics, degradation ratio,
  deterministic verdict hints, and a JSON artifact.
- Reference adapter production hardening: batched downloads (<=25 tickers),
  exponential-backoff retries, vectorized row mapping, and an optional local disk
  cache (`cache_dir`, `max_age_hours`).
- MCP hardening: `run_screen` tool, `ALPHAVERDICT_MCP_ROOT` path confinement,
  1 MiB request-line cap, and optional stderr debug tracing.
- CLI: `--json` machine-readable summaries for `backtest`, terminal findings
  table, real-demo passthrough options (`--period`, `--top-k`, `--benchmark`,
  `--symbols`), and backtest/audit timings recorded in every manifest.
- GitHub Action now appends the verdict to `$GITHUB_STEP_SUMMARY`.

### Changed

- `BacktestEngine` split into cost-independent `prepare()` and pure-arithmetic
  `replay()`; the robustness reviewer replays the cost curve from one prepared
  plan instead of rerunning the full pipeline per multiplier.
- `ResearchSnapshot` gained cached close/open matrices and
  `trailing_momentum(lookback)`; bundled strategies no longer re-pivot full price
  history on every decision date.
- Package version is single-sourced from `src/alphaverdict/_version.py` via
  hatch dynamic versioning.

## [0.2.0] - 2026-08-23

### Added

- Reference public-data adapter (`alphaverdict[real]`) mapping Yahoo Finance daily
  snapshots into the canonical contract, plus `alphaverdict demo --real`.
- Dependency-free Model Context Protocol server (`alphaverdict mcp`) exposing
  deterministic verdict tools to AI agents over stdio.
- Composite GitHub Action that backtests a project and upserts the adversarial
  verdict as a pull-request comment, with badge outputs.
- Launch asset pipeline (`scripts/make_assets.py`): README hero and verdict SVGs,
  example PASS/FAIL reports, and shields endpoint JSON; badge generator
  (`scripts/make_badge.py`).
- PyPI trusted publishing in the release workflow and growth runbook (GROWTH.md).

### Changed

- Demo CLI now reports the evidence score alongside the verdict and routes the
  synthetic fixture through a shared demo runner.

## [0.1.0] - 2026-08-20

### Added

- Bitemporal prices, features, events, and historical-universe contracts.
- Provider-neutral CSV/Parquet adapter and entry-point plugin interface.
- One strategy SDK for current screening and historical decisions.
- Causal open-to-open stock portfolio backtester with explicit cash and costs.
- Five deterministic audit agents and stable evidence finding codes.
- Synthetic full-stack demo, strict project scaffolding, CLI, and self-contained reports.
- Reproducibility manifests, typed public package, 90% coverage gate, security automation,
  and comprehensive documentation.

[Unreleased]: https://github.com/omrgpt/alpha-verdict/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/omrgpt/alpha-verdict/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/omrgpt/alpha-verdict/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/omrgpt/alpha-verdict/releases/tag/v0.1.0
