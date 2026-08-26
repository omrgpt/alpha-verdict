"""Quality-with-momentum: a genuinely multimodal example strategy.

Ranks stocks by combining three independent evidence types:

1. FUNDAMENTALS — gross margin level and trend from quarterly filings
   (bitemporal: uses only what was publicly available at each decision date).
2. NEWS/EVENTS — average earnings-call sentiment over the trailing quarter.
3. TECHNICALS — 63-session price momentum with volatility normalization.

Each pillar is converted to a cross-sectional percentile rank so units never
mix, then weighted 40/20/40. This single class drives BOTH the daily screen
and every historical backtest decision — that is the core AlphaVerdict
contract.
"""

from __future__ import annotations

import pandas as pd

from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot

WEIGHT_FUNDAMENTAL = 0.40
WEIGHT_SENTIMENT = 0.20
WEIGHT_TECHNICAL = 0.40
MOMENTUM_SESSIONS = 63


def _rank_pct(series: pd.Series) -> pd.Series:
    return series.rank(pct=True)


class QualityMomentumStrategy(StockStrategy):
    """Combine filing quality, news tone, and price momentum into one ranking."""

    name = "quality-momentum-multimodal"
    description = (
        "Example only: gross-margin quality + earnings sentiment + momentum. "
        "Not a proposed trading strategy."
    )
    minimum_history = MOMENTUM_SESSIONS + 10
    benchmark_symbol = "INDEX"

    def clone(self) -> QualityMomentumStrategy:
        return QualityMomentumStrategy()

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        # --- pillar 1: fundamentals ----------------------------------------
        features = snapshot.latest_features(["gross_margin"])
        margin = pd.to_numeric(features.get("gross_margin"), errors="coerce")

        # --- pillar 2: recent earnings sentiment ---------------------------
        events = snapshot.known_events(event_type="earnings_sentiment")
        cutoff = snapshot.as_of - pd.Timedelta(days=92)
        recent = events[events["event_at"] >= cutoff]
        if recent.empty:
            sentiment = pd.Series(dtype=float)
        else:
            sentiment = recent.groupby("symbol")["payload"].apply(
                lambda values: pd.to_numeric(
                    [float(item.get("sentiment", 0.0)) for item in values]
                ).mean()
            )

        # --- pillar 3: volatility-normalized momentum ----------------------
        matrix = snapshot.close_matrix()
        if len(matrix) > MOMENTUM_SESSIONS + 1:
            past = matrix.iloc[-MOMENTUM_SESSIONS - 1]
            now = matrix.iloc[-1]
            momentum = now / past - 1
            vol = matrix.pct_change().rolling(40).std().iloc[-1]
            technical = (momentum / vol.replace(0, pd.NA)).astype(float)
        else:
            technical = pd.Series(dtype=float)

        frame = pd.DataFrame(
            {
                "margin": margin,
                "sentiment": sentiment,
                "technical": technical,
            }
        ).dropna(how="all")

        if frame.empty:
            return pd.DataFrame([], columns=["symbol", "score", "eligible", "rationale"])

        frame["eligible"] = frame[["margin", "technical"]].notna().all(axis=1)
        frame["pillar_f"] = _rank_pct(pd.to_numeric(frame["margin"], errors="coerce"))
        frame["pillar_s"] = _rank_pct(pd.to_numeric(frame["sentiment"], errors="coerce")).fillna(
            0.5
        )
        frame["pillar_t"] = _rank_pct(frame["technical"])
        frame["score"] = (
            frame["pillar_f"] * WEIGHT_FUNDAMENTAL
            + frame["pillar_s"] * WEIGHT_SENTIMENT
            + frame["pillar_t"] * WEIGHT_TECHNICAL
        )
        frame["rationale"] = frame.apply(_explain, axis=1)
        frame = frame[frame["eligible"]]
        frame = frame.sort_values("score", ascending=False)
        frame = frame.reset_index().rename(columns={"index": "symbol"})
        return frame[["symbol", "score", "eligible", "rationale"]]


def _explain(row: pd.Series) -> str:
    pillars = []
    if pd.notna(row.get("pillar_f")):
        pillars.append(f"margin p{row['pillar_f']:.0%}")
    if row.get("pillar_s") not in (0.5, None) and pd.notna(row.get("pillar_s")):
        pillars.append(f"news p{row['pillar_s']:.0%}")
    if pd.notna(row.get("pillar_t")):
        pillars.append(f"momentum p{row['pillar_t']:.0%}")
    return " · ".join(pillars) if pillars else "insufficient coverage"
