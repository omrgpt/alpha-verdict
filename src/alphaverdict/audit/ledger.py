"""Append-only trial ledger with a tamper-evident hash chain.

Every backtest run can record itself as one JSONL line: strategy fingerprint,
config fingerprint, data fingerprint, run id, and an optional human label. Each
line commits to the previous line's hash, so silently deleting or editing
history breaks the chain. The declared search burden of a study
(``AuditConfig.n_trials``) can then be reconciled against how many variants
actually ran — the input Deflated Sharpe needs and the number researchers are
most tempted to understate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alphaverdict.engine.models import BacktestResult
from alphaverdict.utils import canonical_json, sha256_text

GENESIS = "genesis"


@dataclass(frozen=True)
class LedgerEntry:
    """One recorded run, committed to the chain by ``entry_hash``."""

    index: int
    timestamp: str
    kind: str
    run_id: str | None
    strategy_name: str
    strategy_fingerprint: str
    config_fingerprint: str | None
    data_fingerprint: str
    label: str
    prev_hash: str
    entry_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "kind": self.kind,
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "strategy_fingerprint": self.strategy_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "data_fingerprint": self.data_fingerprint,
            "label": self.label,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }


HEAD_SUFFIX = ".head"


def _write_head(path: Path, count: int, last_hash: str) -> None:
    """Persist a completeness checkpoint beside the JSONL ledger."""
    head_path = path.with_name(path.name + HEAD_SUFFIX)
    payload = {"count": count, "last_hash": last_hash}
    head_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _read_head(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.with_name(path.name + HEAD_SUFFIX).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    count = parsed.get("count")
    last_hash = parsed.get("last_hash")
    if not isinstance(count, int) or isinstance(count, bool) or not isinstance(last_hash, str):
        return None
    return {"count": count, "last_hash": last_hash}


class TrialLedger:
    """JSONL-backed, hash-chained log of every research variant attempted."""

    extension = ".jsonl"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    # ---------------------------------------------------------------- write

    def record_result(
        self, result: BacktestResult, *, kind: str = "backtest", label: str = ""
    ) -> LedgerEntry:
        """Append one entry derived from a completed backtest result."""
        manifest = result.manifest or {}
        entry = {
            "index": len(self.entries()),
            "timestamp": _now_iso(),
            "kind": kind,
            "run_id": _optional_str(manifest.get("run_id")),
            "strategy_name": result.strategy_name,
            "strategy_fingerprint": result.strategy_fingerprint,
            "config_fingerprint": _optional_str(manifest.get("config_fingerprint")),
            "data_fingerprint": result.data_fingerprint,
            "label": str(label)[:200],
        }
        return self._append(entry)

    def record_note(self, label: str, *, kind: str = "note") -> LedgerEntry:
        """Record a manual milestone (hypothesis change, parameter freeze, ...)."""
        entry = {
            "index": len(self.entries()),
            "timestamp": _now_iso(),
            "kind": kind,
            "run_id": None,
            "strategy_name": "",
            "strategy_fingerprint": "",
            "config_fingerprint": None,
            "data_fingerprint": "",
            "label": str(label)[:200],
        }
        return self._append(entry)

    def _append(self, entry: dict[str, Any]) -> LedgerEntry:
        previous = self.last_hash()
        entry["prev_hash"] = previous
        digest = sha256_text(canonical_json(entry))
        entry["entry_hash"] = digest
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        _write_head(self.path, len(self.entries()), digest)
        return LedgerEntry(**entry)

    # ---------------------------------------------------------------- read

    def entries(self) -> list[LedgerEntry]:
        if not self.path.is_file():
            return []
        output: list[LedgerEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                output.append(LedgerEntry(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return output

    def last_hash(self) -> str:
        stored = self.entries()
        return stored[-1].entry_hash if stored else GENESIS

    def trial_count(self) -> int:
        """Distinct strategy variants attempted (the honest ``n_trials``)."""
        fingerprints = {
            item.strategy_fingerprint
            for item in self.entries()
            if item.kind in {"backtest", "demo"} and item.strategy_fingerprint
        }
        return max(len(fingerprints), 1)

    def run_count(self) -> int:
        return sum(1 for item in self.entries() if item.kind in {"backtest", "demo"})

    def variant_names(self) -> list[str]:
        seen: dict[str, str] = {}
        for item in self.entries():
            if item.kind in {"backtest", "demo"} and item.strategy_fingerprint:
                seen.setdefault(item.strategy_fingerprint, item.strategy_name)
        return [seen[key] for key in sorted(seen)]

    # ------------------------------------------------------------- integrity

    def verify(self) -> tuple[bool, int | None]:
        """Recompute the chain; return ``(ok, first_bad_index)``.

        Strict mode: every line must parse, and if a ``.head`` checkpoint
        exists it must match the parsed entry count and final hash exactly —
        so silent suffix truncation or corrupt lines fail verification even
        when the surviving prefix is internally consistent.
        """
        previous = GENESIS
        entries = self.entries()
        raw_lines = (
            [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if self.path.is_file()
            else []
        )
        if len(entries) != len(raw_lines):
            return False, len(entries)  # corrupt/unparseable line present
        for position, item in enumerate(entries):
            payload = item.to_dict()
            claimed = str(payload.pop("entry_hash"))
            # prev_hash stays inside the hashed payload: each entry commits to
            # its predecessor, so edits or reorders break every later link.
            if str(payload.get("prev_hash")) != previous or (
                sha256_text(canonical_json(payload)) != claimed
            ):
                return False, position
            previous = claimed
        head = _read_head(self.path)
        if head is not None and (
            head["count"] != len(entries)
            or (entries and head["last_hash"] != entries[-1].entry_hash)
            or (not entries and head["last_hash"] != GENESIS)
        ):
            return False, min(head["count"], max(len(entries) - 1, 0)) or 0
        return True, None


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _now_iso() -> str:
    from datetime import UTC, datetime  # noqa: PLC0415 - mirrors utils.utc_now idiom

    return datetime.now(UTC).isoformat(timespec="seconds")
