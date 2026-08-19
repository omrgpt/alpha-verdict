# Reproducibility

Each backtest result carries a manifest with:

- AlphaVerdict version;
- data fingerprint;
- strategy source/parameter fingerprint;
- configuration fingerprint;
- evaluated period count;
- result-frame fingerprint;
- deterministic run ID.

The report writer stores SHA-256 hashes for `result.json`, `audit.json`, and
`report.html` in `manifest.json`.

## What a matching run ID means

A matching run ID means the normalized data content, strategy identity, relevant
engine configuration, and computed returns matched under the current manifest
schema. It does not prove the provider’s historical data was correct or licensed.

## What users should archive

For durable research, archive privately:

- the exact input-data snapshot or immutable warehouse version;
- provider and adjustment-policy documentation;
- strategy and configuration commit SHA;
- environment lock or SBOM;
- every attempted variant and its outcome;
- the complete run artifact directory.

Do not place proprietary input data in a public issue when reporting a bug. Reduce
it to a synthetic fixture that preserves the failing invariant.

## Comparing runs

Compare manifests before performance. If only the strategy fingerprint changes,
the experiment is strategy-level. If data changes, the result is not a clean
strategy comparison. If configuration changes, include the exact assumption delta.

The run ID is not a cryptographic signature. Signing and remote attestation are
separate deployment concerns; release artifacts use GitHub provenance attestation.
