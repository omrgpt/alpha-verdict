"""Tests for the append-only trial ledger (hash chain + trial accounting)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alphaverdict.audit.ledger import GENESIS, LedgerEntry, TrialLedger
from alphaverdict.demo import run_synthetic_demo


class _StubResult:
    """Minimal BacktestResult stand-in for ledger appends."""

    def __init__(self, fingerprint: str, name: str = "stub") -> None:
        self.manifest = {"run_id": f"run-{fingerprint}", "config_fingerprint": "cfg-1"}
        self.strategy_name = name
        self.strategy_fingerprint = fingerprint
        self.data_fingerprint = "data-1"


def test_chain_appends_and_verifies(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    first = ledger.record_result(_StubResult("fp-a"), label="baseline")
    second = ledger.record_note("declared holdout")
    third = ledger.record_result(_StubResult("fp-b"))
    assert first.prev_hash == GENESIS
    assert second.prev_hash == first.entry_hash
    assert third.prev_hash == second.entry_hash
    assert [item.index for item in ledger.entries()] == [0, 1, 2]
    assert ledger.verify() == (True, None)


def test_editing_any_entry_breaks_chain_at_that_index(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    ledger = TrialLedger(path)
    ledger.record_result(_StubResult("fp-a"))
    ledger.record_result(_StubResult("fp-b"))
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["label"] = "retconned"
    lines[0] = json.dumps(payload, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, bad_index = ledger.verify()
    assert ok is False
    assert bad_index == 0


def test_truncation_detected_as_broken_chain(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    ledger = TrialLedger(path)
    for index in range(4):
        ledger.record_result(_StubResult(f"fp-{index}"))
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    ok, bad_index = ledger.verify()
    assert ok is False and bad_index is not None


def test_trial_count_counts_distinct_fingerprints(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    for fingerprint in ("fp-a", "fp-a", "fp-b", "fp-c", "fp-b"):
        ledger.record_result(_StubResult(fingerprint))
    ledger.record_note("a note should not count")
    assert ledger.trial_count() == 3
    assert ledger.run_count() == 5


def test_variant_names_are_stable_and_ordered(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    ledger.record_result(_StubResult("zz", name="zeta"))
    ledger.record_result(_StubResult("aa", name="alpha"))
    assert ledger.variant_names() == ["alpha", "zeta"]


def test_empty_ledger_reads_as_clean(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "missing.jsonl")
    assert ledger.entries() == []
    assert ledger.last_hash() == GENESIS
    assert ledger.verify() == (True, None)
    assert ledger.trial_count() == 1


def test_corrupt_line_is_skipped_but_flags_chain(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    ledger = TrialLedger(path)
    ledger.record_note("good entry")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not valid json\n")
    ok, _bad = ledger.verify()
    assert ok is False


@pytest.mark.parametrize("label", ["hello", ""])
def test_entry_roundtrip_via_to_dict(tmp_path: Path, label: str) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    entry = ledger.record_result(_StubResult("fp-x", name="x"), label=label)
    restored = LedgerEntry(**entry.to_dict())
    assert restored == entry


def test_synthetic_demo_run_is_recorded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    outcome = run_synthetic_demo(Path("demo-runs"), seed=7)
    ledger_path = tmp_path / "trials.jsonl"
    assert ledger_path.is_file()
    ledger = TrialLedger(ledger_path)
    assert ledger.run_count() == 1
    assert outcome.result.strategy_name in ledger.variant_names()
