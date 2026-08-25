"""Deterministic, evidence-linked research recommendations."""

from __future__ import annotations

from alphaverdict.audit.models import Finding

RECOMMENDATIONS: dict[str, str] = {
    "DATA_PRICE_INVARIANT": "Repair the source mapping and rerun every result; invalid OHLC rows make the simulation unusable.",
    "DATA_TEMPORAL_LEAK": "Anchor the field to its public availability timestamp, not its fiscal period or event date.",
    "DATA_SURVIVORSHIP_UNKNOWN": "Supply point-in-time universe membership, including delisted and failed stocks where relevant.",
    "DATA_ADJUSTMENT_UNKNOWN": "Declare and test the split/dividend adjustment policy before interpreting returns.",
    "CAUSALITY_PREFIX_CHANGED": "Remove global/full-sample calculations; every decision must remain unchanged when future rows are corrupted.",
    "STRATEGY_NONDETERMINISTIC": "Seed or remove stochastic behavior and isolate external state before comparing strategy versions.",
    "COST_FRAGILE": "Reduce turnover or demand a larger gross edge; the current result does not survive plausible friction.",
    "RETURN_CONCENTRATION": "Inspect the dominant periods and symbols, then repeat the test without them to measure dependence on luck.",
    "REGIME_INSTABILITY": "Describe the failing regime explicitly and test a pre-declared exposure gate rather than tuning on the full sample.",
    "FOLD_INSTABILITY": "Simplify the rule or broaden the sample; a stable edge should not depend on one contiguous window.",
    "MULTIPLE_TESTING": "Record the complete strategy search and lower confidence according to the true number of attempted variants.",
    "TRIALS_UNDERDECLARED": "Raise audit.n_trials to the ledger-recorded variant count; deflated Sharpe must reflect the real search.",
    "TRIALS_LEDGER_MISSING": "Start the automatic trial ledger so every attempted variant is recorded and auditable.",
    "TRIALS_LEDGER_TAMPERED": "Restore the trial ledger from backup or restart it with an explicit note; treat dependent verdicts as void.",
    "TRACK_RECORD_SHORT": "Collect more independent out-of-sample periods before drawing a performance conclusion.",
    "BENCHMARK_MISSING": "Provide a point-in-time benchmark series so alpha, beta, and regime claims can be evaluated.",
}


def recommendations_for(findings: tuple[Finding, ...], limit: int = 8) -> tuple[str, ...]:
    """Return deduplicated next tests ordered by finding severity."""
    ordered = sorted(findings, key=lambda item: (-int(item.severity), item.code))
    values: list[str] = []
    for finding in ordered:
        recommendation = RECOMMENDATIONS.get(finding.code, finding.recommendation)
        if recommendation and recommendation not in values:
            values.append(recommendation)
        if len(values) >= limit:
            break
    return tuple(values)
