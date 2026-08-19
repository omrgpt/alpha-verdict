# Examples

These files demonstrate contracts; they do not contain a market claim or bundled
market data.

- `strategies/multimodal.py` combines trailing price strength, a point-in-time
  quality feature, and recent known news sentiment.
- `adapters/custom_adapter.py` maps a user-owned SQLite database into canonical
  tables without adding a core provider dependency.
- `alphaverdict.yml` shows a complete CSV project.

Run `alphaverdict demo` for a complete executable path using synthetic data. For
real research, copy an example into a private project, map licensed data, document
temporal semantics, and expect the audit to find unresolved assumptions.
