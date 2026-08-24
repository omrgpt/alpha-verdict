"""Reference public-data adapter and demo strategy for real-market demonstrations.

The adapter wraps community Yahoo Finance downloads behind the canonical bitemporal
contract. It is an adoption on-ramp, not a curated research feed: the universe is a
current-listing snapshot, so the data-integrity reviewer will honestly flag the
survivorship limitation on every run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from alphaverdict.data.adapter import AdapterHealth, HealthStatus
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataRequest
from alphaverdict.data.technicals import momentum
from alphaverdict.exceptions import ConfigurationError, InsufficientDataError
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot

DEFAULT_BENCHMARK = "SPY"
DEFAULT_PERIOD = "5y"
SOURCE_NAME = "yfinance-public"

DEFAULT_UNIVERSE: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "BRK-B",
    "LLY",
    "AVGO",
    "JPM",
    "V",
    "UNH",
    "XOM",
    "MA",
    "PG",
    "JNJ",
    "HD",
    "COST",
    "ABBV",
    "MRK",
    "CVX",
    "PEP",
    "KO",
    "ADBE",
    "WFC",
    "CRM",
    "BAC",
    "TMO",
    "MCD",
    "CSCO",
)

_FIELD_MAP = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "adj close": "close",
}


def _require_yfinance() -> Any:
    """Import the optional dependency or raise an actionable error."""
    try:
        import yfinance  # noqa: PLC0415 - optional dependency resolved on demand
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatched import
        raise ConfigurationError(
            "the yfinance reference adapter requires the optional dependency: "
            "pip install alphaverdict[real]"
        ) from exc
    return yfinance


def _normalize_symbol(value: str) -> str:
    return value.strip().upper()


class YFinanceBundleAdapter:
    """Load public daily OHLCV snapshots into the canonical bundle contract."""

    name = "yfinance"

    def __init__(
        self,
        *,
        symbols: tuple[str, ...] | list[str] = DEFAULT_UNIVERSE,
        benchmark: str = DEFAULT_BENCHMARK,
        period: str = DEFAULT_PERIOD,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        seen: dict[str, None] = {}
        for raw in symbols:
            symbol = _normalize_symbol(str(raw))
            if symbol:
                seen.setdefault(symbol, None)
        self.universe_symbols: tuple[str, ...] = tuple(seen)
        self.benchmark = _normalize_symbol(benchmark)
        if not self.universe_symbols:
            raise ConfigurationError("the reference adapter needs at least one symbol")
        self.period = period
        self.metadata: dict[str, Any] = {
            "adapter": self.name,
            "data_classification": "public_market_data",
            "price_adjustment": "split_and_dividend_adjusted",
            "survivorship": "current_listing_snapshot_not_point_in_time",
            "provider": "Yahoo Finance public endpoints",
            "purpose": "reference demonstration only; verify licensing before research claims",
            **(metadata or {}),
        }

    def health(self) -> AdapterHealth:
        try:
            _require_yfinance()
        except ConfigurationError as exc:
            return AdapterHealth(self.name, HealthStatus.FAIL, str(exc))
        return AdapterHealth(
            self.name,
            HealthStatus.PASS,
            f"{len(self.universe_symbols)} reference symbols configured for period={self.period}",
        )

    def load(self, request: DataRequest) -> DataBundle:
        module = _require_yfinance()
        wanted = list(self._wanted(request))
        if not wanted:
            raise InsufficientDataError(
                "no requested symbols intersect the reference universe; "
                f"available: {', '.join(self.universe_symbols)}"
            )
        try:
            downloaded = module.download(
                tickers=wanted,
                period=self.period,
                interval="1d",
                auto_adjust=True,
                actions=False,
                group_by="ticker",
                threads=True,
                progress=False,
            )
        except Exception as exc:
            raise InsufficientDataError(f"public data download failed: {exc}") from exc
        prices = _price_rows(downloaded, wanted)
        if not prices:
            raise InsufficientDataError(
                "public provider returned no usable daily OHLCV rows for the request"
            )
        frame = pd.DataFrame(prices)
        first_session = frame["timestamp"].min()
        universe = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "effective_from": first_session,
                    "effective_to": pd.NaT,
                    "available_at": first_session,
                    "source": SOURCE_NAME,
                }
                for symbol in sorted({row["symbol"] for row in prices})
            ]
        )
        bundle = DataBundle(prices=frame, universe=universe, metadata=self.metadata)
        return bundle.select(request)

    def _wanted(self, request: DataRequest) -> tuple[str, ...]:
        available = (*self.universe_symbols, self.benchmark)
        if not request.symbols:
            return available
        allowed = set(request.symbols)
        return tuple(symbol for symbol in available if symbol in allowed)


def _price_rows(frame: pd.DataFrame, wanted: list[str]) -> list[dict[str, Any]]:
    """Flatten single-level or ticker-grouped frames into canonical price rows."""
    rows: list[dict[str, Any]] = []
    if frame is None or frame.empty:
        return rows
    groups: list[tuple[str, pd.DataFrame]] = []
    if isinstance(frame.columns, pd.MultiIndex):
        tickers = {
            str(item).upper()
            for item in frame.columns.get_level_values(0)
            if str(item).strip().upper() != "PRICE"
        }
        for ticker in sorted(tickers):
            if ticker not in {value.upper() for value in wanted}:
                continue
            try:
                section = frame[ticker]
            except KeyError:
                continue
            groups.append((ticker, pd.DataFrame(section)))
    else:
        label = str(wanted[0] if wanted else "").upper()
        groups.append((label, frame.copy()))
    for symbol, section in groups:
        renamed = section.rename(columns=lambda item: _FIELD_MAP.get(str(item).lower(), ""))
        renamed = renamed.loc[:, [name for name in renamed.columns if name]]
        if not {"open", "high", "low", "close"}.issubset(renamed.columns):
            continue
        renamed = renamed.rename_axis("timestamp").reset_index()
        renamed["timestamp"] = pd.to_datetime(renamed["timestamp"], utc=True, errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            if column not in renamed:
                renamed[column] = pd.NA
            renamed[column] = pd.to_numeric(renamed[column], errors="coerce")
        renamed = renamed.dropna(subset=["timestamp", "open", "high", "low", "close"])
        renamed = renamed.drop_duplicates(subset=["timestamp"], keep="last")
        for row in renamed.itertuples(index=False):
            values = row._asdict()
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": values["timestamp"],
                    "open": float(values["open"]),
                    "high": float(values["high"]),
                    "low": float(values["low"]),
                    "close": float(values["close"]),
                    "volume": 0.0 if pd.isna(values.get("volume")) else float(values["volume"]),
                    "source": SOURCE_NAME,
                }
            )
    return rows


@dataclass
class RealMomentumStrategy(StockStrategy):
    """Public-data demo ranking trailing twelve-month total returns.

    Example contract only: it shows how one strategy class drives both screening
    and causal backtesting on user-supplied data. It is not a proposed strategy.
    """

    name = "reference-twelve-month-momentum"
    description = (
        "Educational reference: cross-sectional twelve-month momentum on public data; "
        "not a proposed strategy."
    )
    minimum_history = 253
    lookback_sessions: int = 252
    benchmark_symbol: str = DEFAULT_BENCHMARK

    def score(self, snapshot: ResearchSnapshot) -> pd.DataFrame:
        prices = snapshot.price_history(sessions=self.lookback_sessions + 1)
        scores = momentum(prices, self.lookback_sessions)
        excluded = {self.benchmark_symbol.strip().upper()}
        universe = [symbol for symbol in snapshot.universe if symbol not in excluded]
        if not universe:
            universe = [
                str(symbol) for symbol in scores.index if str(symbol).upper() not in excluded
            ]
        frame = pd.DataFrame(index=pd.Index(sorted(set(universe)), name="symbol"))
        frame["score"] = pd.to_numeric(scores.reindex(frame.index), errors="coerce")
        frame["eligible"] = frame["score"].notna()
        frame["rationale"] = f"trailing {self.lookback_sessions}-session total return"
        return frame.reset_index()[["symbol", "score", "eligible", "rationale"]]
