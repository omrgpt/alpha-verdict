"""Transparent turnover and friction calculations."""

from __future__ import annotations

from collections.abc import Mapping


def portfolio_turnover(previous: Mapping[str, float], current: Mapping[str, float]) -> float:
    """One-way turnover including the implicit cash position."""
    symbols = set(previous) | set(current)
    stock_changes = sum(
        abs(current.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols
    )
    previous_cash = 1.0 - sum(previous.values())
    current_cash = 1.0 - sum(current.values())
    return 0.5 * (stock_changes + abs(current_cash - previous_cash))


def friction(turnover: float, cost_bps: float) -> float:
    """Return the portfolio return drag for one rebalance."""
    if turnover < 0 or cost_bps < 0:
        raise ValueError("turnover and costs must be non-negative")
    return turnover * cost_bps / 10_000
