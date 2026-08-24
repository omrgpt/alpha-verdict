"""Reference public-data adapter and demo strategy for real-market demonstrations.

The adapter wraps community Yahoo Finance downloads behind the canonical bitemporal
contract. It is an adoption on-ramp, not a curated research feed: the universe is a
current-listing snapshot, so the data-integrity reviewer will honestly flag the
survivorship limitation on every run.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from alphaverdict.data.adapter import AdapterHealth, HealthStatus
from alphaverdict.data.bundle import DataBundle
from alphaverdict.data.contracts import DataRequest
from alphaverdict.exceptions import ConfigurationError, InsufficientDataError
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.strategy.context import ResearchSnapshot
from alphaverdict.utils import canonical_json, sha256_text

DEFAULT_BENCHMARK = "SPY"
DEFAULT_PERIOD = "5y"
SOURCE_NAME = "yfinance-public"
_MAX_BATCH = 25
_DOWNLOAD_ATTEMPTS = 3

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
        cache_dir: str | Path | None = None,
        max_age_hours: float = 12.0,
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
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else None
        self.max_age_hours = max_age_hours
        if self.max_age_hours < 0:
            raise ConfigurationError("max_age_hours must be non-negative")
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
        detail = (
            f"{len(self.universe_symbols)} reference symbols in batches of <= {_MAX_BATCH} "
            f"for period={self.period}"
        )
        if self.cache_dir is not None:
            detail += f"; disk cache at {self.cache_dir}"
        return AdapterHealth(self.name, HealthStatus.PASS, detail)

    def load(self, request: DataRequest) -> DataBundle:
        wanted = list(self._wanted(request))
        if not wanted:
            raise InsufficientDataError(
                "no requested symbols intersect the reference universe; "
                f"available: {', '.join(self.universe_symbols)}"
            )
        frame = self._cached_or_download(wanted)
        prices = _price_rows(frame, wanted)
        if not prices:
            raise InsufficientDataError(
                "public provider returned no usable daily OHLCV rows for the request"
            )
        price_frame = pd.DataFrame(prices)
        first_session = price_frame["timestamp"].min()
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
        bundle = DataBundle(prices=price_frame, universe=universe, metadata=self.metadata)
        return bundle.select(request)

    def _wanted(self, request: DataRequest) -> tuple[str, ...]:
        available = (*self.universe_symbols, self.benchmark)
        if not request.symbols:
            return available
        allowed = set(request.symbols)
        return tuple(symbol for symbol in available if symbol in allowed)

    def _cache_key(self, wanted: list[str]) -> str:
        payload = {
            "benchmark": self.benchmark,
            "period": self.period,
            "symbols": wanted,
        }
        return sha256_text(canonical_json(payload))[:24]

    def _cache_path(self, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        directory = self.cache_dir.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"yfinance-{key}.pkl"

    def _cache_fresh(self, path: Path) -> bool:
        try:
            age_seconds = time.time() - path.stat().st_mtime
        except OSError:
            return False
        return age_seconds <= self.max_age_hours * 3600

    def _cached_or_download(self, wanted: list[str]) -> pd.DataFrame:
        cache_file = self._cache_path(self._cache_key(wanted))
        if cache_file is not None and self._cache_fresh(cache_file):
            with contextlib.suppress(Exception):
                cached = pd.read_pickle(cache_file)  # noqa: S301 - trusted local cache
                if isinstance(cached, pd.DataFrame) and not cached.empty:
                    return cached
        module = _require_yfinance()
        downloaded = _download_batched(module, wanted, self.period)
        if cache_file is not None and isinstance(downloaded, pd.DataFrame) and not downloaded.empty:
            with contextlib.suppress(OSError):
                downloaded.to_pickle(cache_file)
        return downloaded


def _download_batched(module: Any, wanted: list[str], period: str) -> pd.DataFrame:
    """Download in provider-friendly batches with exponential-backoff retries."""
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for start in range(0, len(wanted), _MAX_BATCH):
        batch = wanted[start : start + _MAX_BATCH]
        last_error: Exception | None = None
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            try:
                frames.append(_download_one(module, batch, period))
                last_error = None
                break
            except InsufficientDataError:
                raise
            except Exception as exc:  # noqa: BLE001 - third-party client raises many types
                last_error = exc
                if attempt + 1 < _DOWNLOAD_ATTEMPTS:
                    time.sleep(0.5 * (2**attempt))
        if last_error is not None:
            failures.append(f"{batch[0]}..{batch[-1]}: {last_error}")
    if not frames:
        detail = "; ".join(failures) if failures else "no batches attempted"
        raise InsufficientDataError(f"public data download failed: {detail}")
    combined = frames[0] if len(frames) == 1 else pd.concat(frames, axis=1)
    return combined


def _download_one(module: Any, tickers: list[str], period: str) -> pd.DataFrame:
    return module.download(
        tickers=tickers,
        period=period,
        interval="1d",
        auto_adjust=True,
        actions=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )


def _price_rows(frame: pd.DataFrame, wanted: list[str]) -> list[dict[str, Any]]:
    """Flatten single-level or ticker-grouped frames into canonical price rows."""
    if frame is None or frame.empty:
        return []
    sections = _sections(frame, wanted)
    parts: list[pd.DataFrame] = []
    for symbol, section in sections:
        renamed = section.rename(columns=lambda item: _FIELD_MAP.get(str(item).lower(), ""))
        renamed = renamed.loc[:, [name for name in renamed.columns if name]]
        if not {"open", "high", "low", "close"}.issubset(renamed.columns):
            continue
        part = renamed.rename_axis("timestamp").reset_index()
        part["timestamp"] = pd.to_datetime(part["timestamp"], utc=True, errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            if column not in part:
                part[column] = pd.NA
            part[column] = pd.to_numeric(part[column], errors="coerce")
        part = part.dropna(subset=["timestamp", "open", "high", "low", "close"])
        part = part.drop_duplicates(subset=["timestamp"], keep="last")
        part["symbol"] = symbol
        part["volume"] = part["volume"].fillna(0.0)
        parts.append(part.loc[:, ["symbol", "timestamp", "open", "high", "low", "close", "volume"]])
    if not parts:
        return []
    combined = pd.concat(parts, ignore_index=True)
    combined["source"] = SOURCE_NAME
    records: list[dict[str, Any]] = combined.to_dict(orient="records")
    return [
        {
            "symbol": str(row["symbol"]),
            "timestamp": row["timestamp"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "source": SOURCE_NAME,
        }
        for row in records
    ]


def _sections(frame: pd.DataFrame, wanted: list[str]) -> list[tuple[str, pd.DataFrame]]:
    """Split a downloaded frame into (symbol, field-frame) pairs."""
    upper_wanted = {str(value).upper() for value in wanted}
    if isinstance(frame.columns, pd.MultiIndex):
        tickers = sorted(
            {
                str(item).upper()
                for item in frame.columns.get_level_values(0)
                if str(item).strip().upper() != "PRICE"
            }
            & upper_wanted
        )
        output: list[tuple[str, pd.DataFrame]] = []
        for ticker in tickers:
            try:
                section = frame[ticker]
            except KeyError:
                continue
            output.append((ticker, pd.DataFrame(section)))
        return output
    label = next((value for value in wanted if str(value).upper() in upper_wanted), "")
    return [(str(label).upper(), frame.copy())]


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
        scores = snapshot.trailing_momentum(self.lookback_sessions)
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
