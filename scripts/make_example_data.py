"""Generate deterministic sample datasets for examples/quickstart (run once by maintainers)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "examples" / "quickstart" / "data"
SYMBOLS = ["AURX", "BELV", "CYNT", "DRAK", "ELMW", "FORR", "GLDW", "HRZN"]
BENCH = "INDEX"
QUARTERS = pd.date_range("2022-03-31", periods=12, freq="QE", tz="UTC")
SESSIONS = pd.bdate_range("2022-06-01", "2024-12-31", tz="UTC")


def _fundamentals(rng: np.random.Generator) -> pd.DataFrame:
    base_margin = rng.uniform(0.08, 0.42, len(SYMBOLS))
    growth = rng.uniform(-0.05, 0.25, len(SYMBOLS))
    rows: list[dict[str, object]] = []
    for i, sym in enumerate(SYMBOLS):
        margin = float(base_margin[i])
        rev = rng.uniform(800, 4_000)
        for quarter in QUARTERS:
            margin = float(np.clip(margin * (1 + rng.normal(0.004, 0.02)), 0.02, 0.65))
            rev *= 1 + growth[i] / 4 + rng.normal(0, 0.02)
            observed = (quarter - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
            available = (quarter + pd.Timedelta(days=35)).strftime("%Y-%m-%d")
            for feature, value in (
                ("gross_margin", round(margin, 4)),
                ("revenue_millions", round(float(rev), 1)),
            ):
                rows.append(
                    {
                        "symbol": sym,
                        "feature": feature,
                        "value": value,
                        "observed_at": observed,
                        "available_at": available,
                        "revision": 0,
                        "source": "sample-fundamentals",
                    }
                )
    return pd.DataFrame(rows)


def _events(rng: np.random.Generator) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sym in SYMBOLS:
        tone = rng.normal(0.15, 0.3)
        for quarter in QUARTERS[1:]:
            sentiment = round(float(np.clip(tone + rng.normal(0, 0.25), -1, 1)), 3)
            rows.append(
                {
                    "symbol": sym,
                    "event_at": (quarter + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    "available_at": (quarter + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
                    "event_type": "earnings_sentiment",
                    "payload": '{"sentiment": ' + str(sentiment) + "}",
                    "source": "sample-news",
                }
            )
    return pd.DataFrame(rows)


def _prices(rng: np.random.Generator) -> pd.DataFrame:
    factor = rng.normal(0.0002, 0.008, len(SESSIONS))
    base_margin = rng.uniform(0.08, 0.42, len(SYMBOLS))
    rows: list[dict[str, object]] = []
    for j, sym in enumerate([*SYMBOLS, BENCH]):
        price = 50.0 + 8 * j
        quality = base_margin[j] if sym in SYMBOLS else 0.2
        drift = 0.0002 + 0.0009 * (quality - 0.25)
        beta = 1.1 if sym != BENCH else 1.0
        for k, day in enumerate(SESSIONS):
            ret = drift + beta * factor[k] + rng.normal(0, 0.011)
            price = max(price * (1 + ret), 1.0)
            open_ = price * (1 + rng.normal(0, 0.0015))
            high = max(open_, price) * (1 + abs(rng.normal(0, 0.004)))
            low = min(open_, price) * (1 - abs(rng.normal(0, 0.004)))
            rows.append(
                {
                    "symbol": sym,
                    "timestamp": day.strftime("%Y-%m-%d"),
                    "open": round(open_, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(price, 2),
                    "volume": int(rng.integers(200_000, 4_000_000)),
                    "source": "sample-prices",
                }
            )
    return pd.DataFrame(rows)


def _universe() -> pd.DataFrame:
    def row(symbol: str) -> dict[str, str]:
        start = SESSIONS[0].strftime("%Y-%m-%d")
        return {
            "symbol": symbol,
            "effective_from": start,
            "effective_to": "",
            "available_at": start,
            "source": "sample-universe",
        }

    return pd.DataFrame([row(sym) for sym in SYMBOLS] + [row(BENCH)])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    _fundamentals(rng).to_csv(OUT / "fundamentals.csv", index=False)
    _events(rng).to_csv(OUT / "events.csv", index=False)
    _prices(rng).to_csv(OUT / "prices.csv", index=False)
    _universe().to_csv(OUT / "universe.csv", index=False)


if __name__ == "__main__":
    main()
