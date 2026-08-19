"""Causal technical features with no future-filled values."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def close_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    """Pivot canonical prices into a date-by-symbol close matrix."""
    return prices.pivot(index="timestamp", columns="symbol", values="close").sort_index()


def open_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    """Pivot canonical prices into a date-by-symbol open matrix."""
    return prices.pivot(index="timestamp", columns="symbol", values="open").sort_index()


def returns(prices: pd.DataFrame, periods: int = 1) -> pd.DataFrame:
    """Trailing close-to-close returns."""
    return close_matrix(prices).pct_change(periods=periods, fill_method=None)


def sma(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Trailing simple moving average."""
    return close_matrix(prices).rolling(window, min_periods=window).mean()


def ema(prices: pd.DataFrame, span: int) -> pd.DataFrame:
    """Trailing exponential moving average."""
    return close_matrix(prices).ewm(span=span, adjust=False, min_periods=span).mean()


def momentum(prices: pd.DataFrame, lookback: int) -> pd.Series:
    """Latest trailing total return for every symbol."""
    matrix = close_matrix(prices)
    if len(matrix) <= lookback:
        return pd.Series(dtype=float)
    return matrix.iloc[-1] / matrix.iloc[-lookback - 1] - 1


def volatility(prices: pd.DataFrame, window: int = 63, annualization: int = 252) -> pd.Series:
    """Latest trailing annualized volatility."""
    values = returns(prices).rolling(window, min_periods=window).std(ddof=1) * np.sqrt(
        annualization
    )
    return pd.Series(dtype=float) if values.empty else values.iloc[-1]


def rsi(prices: pd.DataFrame, period: int = 14) -> pd.Series:
    """Latest Wilder-style relative strength index."""
    delta = close_matrix(prices).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    strength = average_gain / average_loss.replace(0, np.nan)
    values = 100 - (100 / (1 + strength))
    return pd.Series(dtype=float) if values.empty else values.iloc[-1]


def cross_sectional_rank(values: pd.Series, *, ascending: bool = True) -> pd.Series:
    """Rank available values into [0, 1] without fabricating missing observations."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return pd.Series(dtype=float)
    if len(clean) == 1:
        return pd.Series(0.5, index=clean.index, dtype=float)
    return clean.rank(method="average", pct=True, ascending=ascending)


def winsorize(values: pd.Series, limits: tuple[float, float] = (0.01, 0.99)) -> pd.Series:
    """Clip a cross-section to empirical quantiles."""
    clean = pd.to_numeric(values, errors="coerce")
    lower, upper = limits
    if not 0 <= lower < upper <= 1:
        raise ValueError("winsorization limits must satisfy 0 <= lower < upper <= 1")
    return clean.clip(clean.quantile(lower), clean.quantile(upper))


def combine_ranks(series: Iterable[tuple[pd.Series, float]]) -> pd.Series:
    """Combine aligned rank series while re-normalizing around missing features."""
    weighted: list[pd.Series] = []
    weights: list[pd.Series] = []
    for values, weight in series:
        if weight < 0:
            raise ValueError("rank weights must be non-negative")
        weighted.append(values * weight)
        weights.append(values.notna().astype(float) * weight)
    if not weighted:
        return pd.Series(dtype=float)
    numerator = pd.concat(weighted, axis=1).sum(axis=1, min_count=1)
    denominator = pd.concat(weights, axis=1).sum(axis=1)
    return numerator / denominator.replace(0, np.nan)
