# GitHub Action: verdicts on every pull request

`omrgpt/alpha-verdict@main` publishes a composite action that runs the audit
council on your strategy project and posts the deterministic verdict as a pull
request comment. The comment is upserted: every push to the same PR replaces the
previous verdict instead of spamming new comments.

## Usage

```yaml
name: Research verdict

on:
  pull_request:
    paths:
      - "strategy.py"
      - "alphaverdict.yml"
      - "data/**"

permissions:
  contents: read
  pull-requests: write

jobs:
  verdict:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Prepare point-in-time data
        run: ./scripts/export-canonical-prices.sh   # your own data pipeline
      - uses: omrgpt/alpha-verdict@main
        with:
          config-path: alphaverdict.yml
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `config-path` | `alphaverdict.yml` | Project configuration path relative to `working-directory`. |
| `working-directory` | `.` | Directory containing the configuration and data files. |
| `python-version` | `3.12` | Python used to install and run AlphaVerdict. |
| `extra-install-args` | _(empty)_ | Extra pip arguments forwarded during installation. |
| `pr-number` | triggering PR | Pull request number for the comment. |
| `github-token` | `github.token` | Token used to post the comment. |
| `post-comment` | `true` | Set to `false` to compute outputs without commenting. |

## Outputs

| Output | Description |
| --- | --- |
| `verdict` | The merged council verdict: `pass`, `warn`, or `fail`. |
| `score` | Evidence score out of 100. |

## Behaviour notes

- The action installs AlphaVerdict from **this repository at the ref you pin**,
  so `uses: omrgpt/alpha-verdict@v0.2.0` stays frozen while `@main` tracks HEAD.
- If the backtest itself fails, the job does not silently pass: the comment step
  reports that no artifacts were produced, which is itself a research failure.
- The comment includes a static shields badge with the current verdict and score,
  suitable for copying into a README.

## Badge in your README

After any local run:

```bash
alphaverdict backtest
python scripts/make_badge.py runs/<run-id>/audit.json --url >> README.md
```

Or use the shields JSON endpoint generated from your latest committed run.
