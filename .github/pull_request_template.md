## Outcome

<!-- What research or contributor outcome changes? -->

## Evidence

<!-- Tests, synthetic reproduction, benchmark, or docs supporting the change. -->

## Assumption impact

- [ ] No timing, universe, adjustment, cost, statistical, or verdict semantics changed.
- [ ] Changed assumptions are listed below and documented.

## Safety and scope

- [ ] No credentials, licensed data, personal paths, private strategy, or generated runs.
- [ ] No broker/live-execution surface or performance claim.
- [ ] New/changed plugin code documents its trust boundary.

## Verification

- [ ] `ruff format --check src tests examples`
- [ ] `ruff check src tests examples`
- [ ] `mypy src/alphaverdict`
- [ ] `pytest`
- [ ] `mkdocs build --strict`
- [ ] Documentation/changelog updated where needed.
