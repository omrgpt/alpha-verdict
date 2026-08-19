# CLI reference

## `alphaverdict init [DESTINATION]`

Create a project YAML, strategy skeleton, data-contract README, and local
`.gitignore`. Existing files are not overwritten unless `--force` is supplied.

## `alphaverdict validate --config FILE`

Parse strict configuration, instantiate the adapter, run its health check, load and
normalize requested data, and load the strategy contract. Validation executes trusted
local plugin code but does not run a backtest.

## `alphaverdict screen --config FILE`

Rank stocks at the bundle’s latest date or `--as-of`. `--output` writes the same
ranked evidence as JSON. Screening never emits orders, quantities, or broker calls.

## `alphaverdict backtest --config FILE`

Run the causal portfolio simulation, all default audit agents, and report generation.
The command prints the verdict and local report path. The configured output directory
receives a subdirectory named from the reproducible run ID.

## `alphaverdict demo`

Generate a deterministic synthetic multimodal fixture and exercise the full stack.
Use `--seed` to verify repeatability and `--output` to choose the artifact directory.
The command is a software smoke test only.

## Exit behavior

Expected configuration, contract, and I/O errors return exit code `2` with a bounded
message. Unexpected programming failures are not hidden by a blanket exception.
