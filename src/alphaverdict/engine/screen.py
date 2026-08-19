"""One-date stock screening."""

from __future__ import annotations

import pandas as pd

from alphaverdict.data.bundle import DataBundle
from alphaverdict.engine.models import ScreenResult
from alphaverdict.exceptions import InsufficientDataError
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot


def screen(
    bundle: DataBundle,
    strategy: StockStrategy,
    *,
    as_of: pd.Timestamp | str | None = None,
    top_n: int = 20,
    minimum_score: float | None = None,
) -> ScreenResult:
    """Rank stocks at a point in time; no orders or execution objects exist."""
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    timestamp = bundle.end if as_of is None else pd.Timestamp(as_of)
    if timestamp is None:
        raise InsufficientDataError("screening requires price data")
    snapshot = ResearchSnapshot.from_bundle(bundle, timestamp)
    ranked = strategy.screen(snapshot).top(top_n, minimum_score=minimum_score)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ScreenResult(
        as_of=snapshot.as_of,
        ranked=ranked,
        strategy_name=strategy.name,
        strategy_fingerprint=strategy.fingerprint(),
        data_fingerprint=bundle.fingerprint(),
    )
