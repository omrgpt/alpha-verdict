# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project intends to
use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- External adapter conformance kit and independently reproduced reference fixtures.

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

[Unreleased]: https://github.com/omrgpt/alpha-verdict/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/omrgpt/alpha-verdict/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/omrgpt/alpha-verdict/releases/tag/v0.1.0
