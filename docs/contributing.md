# Contributing

The complete policy is in
[`CONTRIBUTING.md`](https://github.com/omrgpt/alpha-verdict/blob/main/CONTRIBUTING.md).

The shortest path:

```bash
git clone https://github.com/omrgpt/alpha-verdict.git
cd alpha-verdict
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,docs,parquet]"
pre-commit install
pytest
```

Every change should make a contract clearer, catch a real failure, reduce setup
friction, or improve reproducibility. Performance claims, provider credentials,
licensed datasets, and broker execution are out of scope.
