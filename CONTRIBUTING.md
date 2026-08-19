# Contributing to AlphaVerdict

Thank you for helping build research infrastructure that is easier to distrust well.
Contributions are welcome from beginners, researchers, engineers, and documentation
specialists.

By participating, you agree to the [Code of Conduct](CODE_OF_CONDUCT.md) and license
your contribution under Apache-2.0.

## Before opening code

Use an issue for significant behavior, public contracts, new dependencies, audit
findings, or architecture. Small documentation and test corrections can go directly
to a pull request.

Security vulnerabilities belong in private reporting under [SECURITY.md](SECURITY.md),
not a public issue.

## Development setup

```bash
git clone https://github.com/omrgpt/alpha-verdict.git
cd alpha-verdict
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,docs,parquet]"
pre-commit install
```

Run the full local gate:

```bash
ruff format --check src tests examples
ruff check src tests examples
mypy src/alphaverdict
pytest
mkdocs build --strict
python -m build
pip-audit
bandit -c pyproject.toml -r src
```

## Pull-request standard

A reviewable pull request:

- solves one coherent problem;
- explains the user-facing outcome and risk;
- adds or updates tests for every changed branch or invariant;
- preserves at least 90% branch-aware project coverage;
- updates documentation and changelog when contracts change;
- uses synthetic/minimal fixtures with no proprietary data;
- contains no credentials, personal paths, generated reports, or private strategy;
- states whether timing, cost, universe, or statistical assumptions changed.

Do not mix formatting-only changes with financial logic. Never weaken a failing test
or audit threshold merely to make CI green without explaining the underlying contract.

## Audit-agent requirements

A new reviewer or finding code needs:

1. a falsifiable question;
2. deterministic bounded inputs and outputs;
3. a stable code and severity rationale;
4. evidence a user can verify;
5. a next research test, not a claim to improve returns;
6. primary-source methodology where statistical;
7. positive, negative, edge, and reproducibility tests;
8. documentation of assumptions and failure modes.

An agent may not mutate data, strategy, configuration, or another agent’s report.

## Adapter requirements

Adapters belong outside core unless they are dependency-light and broadly useful.
Document licensing, timestamp semantics, revisions, corporate actions, delistings,
symbol identity, rate limits, and credential handling. `health()` must be side-effect
free. Tests must run without a paid key or live provider.

## Commit and review hygiene

Use imperative, descriptive commit subjects. Maintainers may squash a pull request.
All CI checks and review conversations must be resolved before merge. At least one
maintainer approval is required; security-sensitive changes may require an additional
review or private audit.

## Scope boundaries

The following are not accepted without a governance-level scope decision:

- broker connections or live execution;
- automatic buy/sell instructions;
- non-stock asset classes;
- bundled proprietary data;
- opaque model-generated ranks or verdicts;
- claims or fixtures designed to market historical profitability.

## Documentation style

Write in plain language, define temporal terms, and lead with limitations. Examples
must say whether they are synthetic or educational. Avoid “guaranteed,” “safe,”
“institutional-grade,” or “beats” unless a narrowly scoped claim is backed by a public,
reproducible benchmark.
