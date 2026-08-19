"""Dependency-light performance and risk metrics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def max_drawdown(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    equity = (1 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1
    return float(drawdown.min())


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return (
        None
        if not math.isfinite(denominator) or denominator <= 0
        else float(numerator / denominator)
    )


def calculate_metrics(
    returns: pd.Series,
    *,
    periods_per_year: int,
    annual_risk_free_rate: float = 0.0,
    benchmark: pd.Series | None = None,
    turnover: pd.Series | None = None,
    exposure: pd.Series | None = None,
) -> dict[str, float | int | None]:
    """Calculate metrics with explicit annualization and finite outputs."""
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return {"periods": 0, "total_return": 0.0}
    total_return = float((1 + clean).prod() - 1)
    years = len(clean) / periods_per_year
    annual_return = -1.0 if total_return <= -1 else float((1 + total_return) ** (1 / years) - 1)
    annual_volatility = (
        float(clean.std(ddof=1) * math.sqrt(periods_per_year)) if len(clean) > 1 else 0.0
    )
    periodic_rf = (1 + annual_risk_free_rate) ** (1 / periods_per_year) - 1
    excess = clean - periodic_rf
    sharpe = _safe_ratio(float(excess.mean() * periods_per_year), annual_volatility)
    downside = clean[clean < periodic_rf] - periodic_rf
    downside_vol = (
        float(downside.std(ddof=1) * math.sqrt(periods_per_year)) if len(downside) > 1 else 0.0
    )
    sortino = _safe_ratio(float(excess.mean() * periods_per_year), downside_vol)
    drawdown = max_drawdown(clean)
    calmar = _safe_ratio(annual_return, abs(drawdown))
    value_at_risk = float(clean.quantile(0.05))
    tail = clean[clean <= value_at_risk]
    conditional_value_at_risk = float(tail.mean()) if not tail.empty else value_at_risk
    result: dict[str, float | int | None] = {
        "periods": len(clean),
        "years": float(years),
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "max_drawdown": drawdown,
        "win_rate": float((clean > 0).mean()),
        "best_period": float(clean.max()),
        "worst_period": float(clean.min()),
        "var_95": value_at_risk,
        "cvar_95": conditional_value_at_risk,
        "skew": float(clean.skew()) if len(clean) > 2 else None,
        "excess_kurtosis": float(clean.kurt()) if len(clean) > 3 else None,
    }
    if turnover is not None:
        values = pd.to_numeric(turnover, errors="coerce").reindex(clean.index).dropna()
        result["average_turnover"] = float(values.mean()) if not values.empty else None
        result["annual_turnover"] = (
            float(values.mean() * periods_per_year) if not values.empty else None
        )
    if exposure is not None:
        values = pd.to_numeric(exposure, errors="coerce").reindex(clean.index).dropna()
        result["average_gross_exposure"] = float(values.mean()) if not values.empty else None
    if benchmark is not None:
        aligned = pd.concat(
            [clean.rename("strategy"), benchmark.rename("benchmark")], axis=1
        ).dropna()
        if len(aligned) > 1 and float(aligned["benchmark"].var(ddof=1)) > 0:
            covariance = float(aligned.cov().loc["strategy", "benchmark"])
            beta = covariance / float(aligned["benchmark"].var(ddof=1))
            alpha_periodic = float(aligned["strategy"].mean() - beta * aligned["benchmark"].mean())
            active = aligned["strategy"] - aligned["benchmark"]
            tracking_error = float(active.std(ddof=1) * math.sqrt(periods_per_year))
            result["beta"] = beta
            result["annual_alpha"] = alpha_periodic * periods_per_year
            result["information_ratio"] = _safe_ratio(
                float(active.mean() * periods_per_year), tracking_error
            )
            result["correlation"] = float(aligned.corr().loc["strategy", "benchmark"])
    return {key: _finite(value) for key, value in result.items()}


def _finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return _finite(value.item())
    return value
