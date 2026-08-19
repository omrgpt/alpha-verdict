# Security and threat model

AlphaVerdict is local research infrastructure. The primary assets are credentials,
licensed datasets, private strategies, filesystem integrity, and the correctness of
research evidence.

## Trust boundaries

| Input | Trusted? | Control |
|---|---|---|
| project YAML | data only, potentially malformed | safe YAML, strict keys, typed validation |
| strategy/adaptor Python | **trusted executable code** | explicit references, project-root path boundary, review required |
| CSV/Parquet content | untrusted data | schema normalization, duplicate rejection, temporal and audit checks |
| event payload | untrusted structured data | JSON-object requirement, HTML auto-escaping in reports |
| report destination | user-controlled local path | explicit output root, no web serving |
| optional model callable | user-controlled external boundary | audit JSON only, bounded output, off by default |

## Threats addressed

- **Path traversal:** local data and file-based strategy references cannot escape the
  configured project root unless the user explicitly weakens the boundary.
- **Unsafe deserialization:** configuration uses safe YAML; events accept JSON
  objects; no pickle loader exists.
- **Secret leakage:** no config interpolation, telemetry, broker SDK, or default
  network call; reports omit source code, credentials, and raw event payloads.
- **HTML injection:** Jinja auto-escaping applies to user-controlled report fields;
  the only marked-safe fragment is a renderer-owned SVG generated from numeric data.
- **Supply-chain drift:** dependencies are bounded, Dependabot is enabled, CI audits
  known vulnerabilities, CodeQL scans source, and release builds are attested.
- **Research-integrity attacks:** source lineage, fingerprints, causal snapshots,
  prefix perturbation, cost stress, and deterministic manifests make silent changes
  more visible.

## Threats not addressed

- A malicious strategy or adapter can execute with the current Python process’s
  permissions. AlphaVerdict is not a sandbox.
- A provider can return plausible but false or improperly licensed data.
- Hashes detect change; they do not prove truth or authorship.
- Local malware or a compromised Python dependency can bypass application controls.
- Model-generated historical labels may contain knowledge from future training data.
- The engine does not protect users from making poor financial decisions.

## Safe deployment

Run unknown research projects inside a disposable container or restricted user
account with no secrets mounted. Pin dependencies, review plugin source, provide
read-only data, and write artifacts to a dedicated directory. Never expose the CLI
as an unauthenticated network service.

Report vulnerabilities privately using the process in
[`SECURITY.md`](https://github.com/omrgpt/alpha-verdict/blob/main/SECURITY.md). Do not open a public issue containing exploit code,
credentials, licensed data, or private strategies.
