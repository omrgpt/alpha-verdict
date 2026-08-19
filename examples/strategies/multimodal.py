"""Educational multimodal stock ranking; not a recommendation or market edge."""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaverdict import ResearchSnapshot, StockStrategy
from alphaverdict.data.technicals import combine_ranks, cross_sectional_rank, momentum


class Strategy(StockStrategy):
    """Combine pre-declared technical, fundamental, and event evidence."""

    name = "educational-multimodal-example"
    description = "API example only; validate every field and hypothesis independently."
    minimum_history = 253

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        strength = momentum(snapshot.price_history(sessions=253), lookback=252)
        features = snapshot.latest_features(["return_on_equity"])
        quality = features.get("return_on_equity", pd.Series(dtype=float))

        news = snapshot.known_events(event_type="news_sentiment")
        news = news[news["event_at"] >= snapshot.as_of - pd.Timedelta(days=30)]
        if news.empty:
            sentiment = pd.Series(dtype=float)
        else:
            sentiment = news.groupby("symbol")["payload"].apply(
                lambda rows: float(
                    np.mean([float(payload.get("sentiment", 0.0)) for payload in rows])
                )
            )

        ranks = combine_ranks(
            [
                (cross_sectional_rank(strength), 0.50),
                (cross_sectional_rank(pd.to_numeric(quality, errors="coerce")), 0.35),
                (cross_sectional_rank(sentiment), 0.15),
            ]
        )
        frame = ranks.rename("score").rename_axis("symbol").reset_index()
        frame["eligible"] = frame["score"].notna()
        frame["rationale"] = "252-session strength + known quality + 30-day known news"
        return frame
