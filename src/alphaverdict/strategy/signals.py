"""Normalized strategy outputs used by screening and backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from alphaverdict.exceptions import StrategyContractError

SIGNAL_COLUMNS = ("symbol", "score", "eligible", "rationale")


@dataclass(frozen=True)
class SignalSet:
    """A deterministic cross-sectional score at one decision timestamp."""

    as_of: pd.Timestamp
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        timestamp = pd.Timestamp(self.as_of)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        object.__setattr__(self, "as_of", timestamp)
        object.__setattr__(self, "frame", self._normalize(self.frame))

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        if result.index.name == "symbol" and "symbol" not in result:
            result = result.reset_index()
        missing = {"symbol", "score"} - set(result.columns)
        if missing:
            raise StrategyContractError(
                f"strategy output is missing columns: {', '.join(sorted(missing))}"
            )
        if "eligible" not in result:
            result["eligible"] = True
        if "rationale" not in result:
            result["rationale"] = ""
        result = result.loc[:, list(SIGNAL_COLUMNS)].copy()
        result["symbol"] = result["symbol"].astype("string").str.strip().str.upper()
        result["score"] = pd.to_numeric(result["score"], errors="coerce")
        result["eligible"] = result["eligible"].astype(bool)
        result["rationale"] = result["rationale"].fillna("").astype(str).str.slice(0, 1_000)
        if result["symbol"].isna().any() or (result["symbol"] == "").any():
            raise StrategyContractError("strategy output contains an empty symbol")
        if result["symbol"].duplicated().any():
            raise StrategyContractError("strategy output contains duplicate symbols")
        invalid_score = result["eligible"] & ~np.isfinite(result["score"])
        if invalid_score.any():
            raise StrategyContractError("eligible strategy scores must be finite")
        return result.sort_values(
            ["score", "symbol"], ascending=[False, True], kind="stable"
        ).reset_index(drop=True)

    @classmethod
    def from_output(cls, as_of: pd.Timestamp, output: Any) -> SignalSet:
        if isinstance(output, SignalSet):
            if output.as_of != as_of:
                raise StrategyContractError("strategy returned signals for the wrong timestamp")
            return output
        if isinstance(output, pd.Series):
            frame = output.rename("score").rename_axis("symbol").reset_index()
            return cls(as_of, frame)
        if isinstance(output, pd.DataFrame):
            return cls(as_of, output)
        if isinstance(output, dict):
            frame = pd.Series(output, name="score").rename_axis("symbol").reset_index()
            return cls(as_of, frame)
        raise StrategyContractError(
            "strategy must return SignalSet, Series, DataFrame, or symbol-score mapping"
        )

    def eligible(self) -> pd.DataFrame:
        return self.frame[self.frame["eligible"]].copy()

    def top(self, count: int, *, minimum_score: float | None = None) -> pd.DataFrame:
        if count <= 0:
            raise ValueError("count must be positive")
        result = self.eligible()
        if minimum_score is not None:
            result = result[result["score"] >= minimum_score]
        return result.head(count).copy()

    def comparable(self) -> pd.DataFrame:
        """Return stable columns suitable for deterministic equality checks."""
        return self.frame.sort_values("symbol").reset_index(drop=True)
