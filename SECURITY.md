# Security policy

Security includes conventional software vulnerabilities and accidental exposure of
credentials, licensed market data, or private strategy logic.

## Supported versions

| Version | Security fixes |
|---|:---:|
| latest `0.x` release | yes |
| older alpha releases | no |

Before `1.0`, only the latest minor release receives fixes.

## Report privately

Use GitHub’s **Security → Report a vulnerability** flow for this repository. Include:

- affected version and operating system;
- minimal reproduction using synthetic data;
- impact and trust boundary crossed;
- whether credentials or licensed data may have been exposed;
- suggested mitigation if known.

Do not open a public issue, attach real provider data, paste a token, or test against
systems you do not own. You should receive acknowledgement within 72 hours and a
status update within seven days.

## Coordinated disclosure

Maintainers will validate impact, prepare a private fix, request a CVE when appropriate,
and agree on a disclosure date with the reporter. Timelines depend on severity and
downstream coordination. Good-faith research that follows this policy will be treated
constructively.

## Security model in one sentence

YAML and data are validated as untrusted inputs; strategies and adapter plugins are
explicitly trusted Python code and are **not sandboxed**.

See the complete [threat model](docs/security.md).
