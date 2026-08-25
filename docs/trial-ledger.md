# The trial ledger

Deflated Sharpe and every multiple-testing correction depend on one number
researchers are most tempted to fudge: **how many variants did you actually
try?** The trial ledger removes the honor system. Every `alphaverdict
backtest` and `alphaverdict demo` run appends itself to an append-only,
hash-chained research diary (`trials.jsonl` next to your project), and a sixth
council reviewer — the trials agent — reconciles that record against the
`n_trials` you declared.

## What gets recorded

One JSONL line per run: timestamp, run id, strategy name + fingerprint, config
fingerprint, data fingerprint, and an optional label. Each line commits to the
previous line's hash; a `.head` checkpoint file records the expected count and
final hash so silent truncation fails verification too.

## Commands

```bash
# recorded automatically on every run
alphaverdict backtest -c alphaverdict.yml

# inspect history and verify the chain
alphaverdict ledger show
alphaverdict ledger verify      # exit 1 if tampered

# declare milestones by hand (hypothesis freeze, holdout declaration...)
alphaverdict ledger note "froze params after 12 variants; SPY holdout starts 2025-01"

# skip recording (not recommended)
alphaverdict backtest --no-ledger ...
```

## Findings the trials agent can raise

| Code | Severity | Meaning |
|---|---|---|
| `TRIALS_LEDGER_MISSING` | medium | No diary exists; nothing proves what was searched. |
| `TRIALS_UNDERDECLARED` | high | Ledger shows more distinct variants than `audit.n_trials`. |
| `TRIALS_LEDGER_TAMPERED` | critical | Hash chain or checkpoint failed — treat verdicts as void. |
| `TRIALS_OVERDECLARED` | info | Declared burden exceeds the recorded search (unrecorded work elsewhere?). |

## Design notes

- **Append-only**: nothing in the workflow ever rewrites `trials.jsonl`.
- **Tamper-evident, not tamper-proof**: a determined attacker can rebuild the
  whole file including its chain; the `.head` checkpoint (which can be kept
  outside the repo) raises the cost substantially. The threat model is the
  *convenient silent edit*, not the adversary.
- **Distinct variants** are counted by strategy fingerprint, not runs: running
  the same strategy ten times is one trial; ten lookback lengths are ten.
- Committing `trials.jsonl` alongside research code is encouraged: reviewers
  can then verify that a published result's declared burden matches reality.
