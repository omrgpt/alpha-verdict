"""Small deterministic helpers shared across the package."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphaverdict.exceptions import SecurityBoundaryError


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(UTC)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, (datetime, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC").isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda x: str(x[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if pd.isna(value):
        return None
    return str(value)


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically for hashing and manifests."""
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    """Hash UTF-8 text with SHA-256."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Hash a file without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def hash_dataframe(frame: pd.DataFrame) -> str:
    """Return an order-insensitive, schema-sensitive frame fingerprint."""
    normalized = frame.copy()
    normalized = normalized.reindex(sorted(map(str, normalized.columns)), axis=1)
    for column in normalized.columns:
        series = normalized[column]
        if isinstance(series.dtype, pd.DatetimeTZDtype) or pd.api.types.is_datetime64_any_dtype(
            series
        ):
            normalized[column] = pd.to_datetime(series, utc=True, errors="coerce").astype("string")
        elif series.dtype == "object":
            normalized[column] = series.map(canonical_json)
    row_hashes = pd.util.hash_pandas_object(normalized, index=False, categorize=True).to_numpy(
        copy=True
    )
    row_hashes.sort()
    digest = hashlib.sha256()
    digest.update(canonical_json(list(normalized.columns)).encode())
    digest.update(canonical_json([str(dtype) for dtype in normalized.dtypes]).encode())
    digest.update(row_hashes.tobytes())
    return digest.hexdigest()


def resolve_within(root: Path, candidate: str | Path, *, allow_outside: bool = False) -> Path:
    """Resolve a local path and enforce a project-root trust boundary."""
    text = str(candidate)
    if "://" in text:
        raise SecurityBoundaryError("remote URLs are not accepted as local data paths")
    resolved_root = root.expanduser().resolve()
    path = Path(candidate).expanduser()
    resolved = (resolved_root / path).resolve() if not path.is_absolute() else path.resolve()
    if not allow_outside and resolved != resolved_root and resolved_root not in resolved.parents:
        raise SecurityBoundaryError(f"path escapes configured project root: {candidate}")
    return resolved
