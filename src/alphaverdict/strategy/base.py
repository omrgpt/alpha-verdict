"""Base class for user-authored stock strategies."""

from __future__ import annotations

import copy
import inspect
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from typing import Any

from alphaverdict.strategy.context import ResearchSnapshot
from alphaverdict.strategy.signals import SignalSet
from alphaverdict.utils import canonical_json, sha256_text


class StockStrategy(ABC):
    """One-file strategy contract used for both screening and research backtests."""

    name = "unnamed-strategy"
    description = ""
    minimum_history = 60

    @abstractmethod
    def score(self, snapshot: ResearchSnapshot) -> Any:
        """Score the active stock universe using only the supplied snapshot."""

    def screen(self, snapshot: ResearchSnapshot) -> SignalSet:
        """Normalize strategy output and enforce universe membership."""
        signals = SignalSet.from_output(snapshot.as_of, self.score(snapshot))
        if snapshot.universe:
            allowed = set(snapshot.universe)
            unknown = sorted(set(signals.frame["symbol"]) - allowed)
            if unknown:
                frame = signals.frame.copy()
                frame.loc[frame["symbol"].isin(unknown), "eligible"] = False
                frame.loc[frame["symbol"].isin(unknown), "rationale"] = (
                    "not in point-in-time universe"
                )
                signals = SignalSet(snapshot.as_of, frame)
        counts = snapshot.history_counts()
        short = set(counts[counts < self.minimum_history].index)
        if short:
            frame = signals.frame.copy()
            mask = frame["symbol"].isin(short)
            frame.loc[mask, "eligible"] = False
            frame.loc[mask, "rationale"] = f"fewer than {self.minimum_history} price sessions"
            signals = SignalSet(snapshot.as_of, frame)
        return signals

    def clone(self) -> StockStrategy:
        """Create an isolated strategy instance for repeatability checks."""
        return copy.deepcopy(self)

    def parameters(self) -> dict[str, Any]:
        """Return public instance state for manifests, excluding private fields."""
        values = asdict(self) if is_dataclass(self) else dict(vars(self))
        return {str(key): value for key, value in values.items() if not str(key).startswith("_")}

    def fingerprint(self) -> str:
        """Hash strategy source identity and public parameters without storing source text."""
        try:
            source = inspect.getsource(self.__class__)
        except (OSError, TypeError):
            source = f"{self.__class__.__module__}:{self.__class__.__qualname__}"
        payload = {
            "class": f"{self.__class__.__module__}:{self.__class__.__qualname__}",
            "source": source,
            "parameters": self.parameters(),
        }
        return sha256_text(canonical_json(payload))
