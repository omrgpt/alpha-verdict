"""Statistical diagnostics with transparent assumptions and deterministic seeds."""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, cast

import numpy as np
import pandas as pd

from alphaverdict.engine.metrics import max_drawdown


def _returns(values: pd.Series) -> np.ndarray:
    result = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    return cast("np.ndarray", result)


def sample_sharpe(values: pd.Series) -> float:
    data = _returns(values)
    if len(data) < 2 or float(data.std(ddof=1)) == 0:
        return 0.0
    return float(data.mean() / data.std(ddof=1))


def probabilistic_sharpe_ratio(values: pd.Series, benchmark_sharpe: float = 0.0) -> float:
    """Probability sample Sharpe exceeds a periodic benchmark Sharpe."""
    data = _returns(values)
    if len(data) < 3:
        return 0.5
    sharpe = sample_sharpe(pd.Series(data))
    skew = float(pd.Series(data).skew())
    kurtosis = float(pd.Series(data).kurt() + 3)
    denominator = math.sqrt(max(1e-12, 1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe**2))
    z_score = (sharpe - benchmark_sharpe) * math.sqrt(len(data) - 1) / denominator
    return float(NormalDist().cdf(z_score))


def expected_max_sharpe(values: pd.Series, n_trials: int) -> float:
    """Approximate lucky maximum periodic Sharpe under ``n_trials`` null searches."""
    if n_trials <= 1:
        return 0.0
    data = _returns(values)
    if len(data) < 3:
        return 0.0
    sharpe = sample_sharpe(pd.Series(data))
    skew = float(pd.Series(data).skew())
    kurtosis = float(pd.Series(data).kurt() + 3)
    standard_error = math.sqrt(
        max(1e-12, 1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe**2)
    ) / math.sqrt(len(data) - 1)
    euler_gamma = 0.5772156649
    distribution = NormalDist()
    first = distribution.inv_cdf(1 - 1 / n_trials)
    second = distribution.inv_cdf(1 - 1 / (n_trials * math.e))
    return float(standard_error * ((1 - euler_gamma) * first + euler_gamma * second))


def deflated_sharpe_probability(values: pd.Series, n_trials: int) -> float:
    """PSR against the expected best Sharpe from repeated trials."""
    return probabilistic_sharpe_ratio(values, expected_max_sharpe(values, n_trials))


def minimum_track_record_length(
    values: pd.Series, benchmark_sharpe: float = 0.0, confidence: float = 0.95
) -> float | None:
    """Estimated periods needed to establish Sharpe above a benchmark."""
    data = _returns(values)
    if len(data) < 3:
        return None
    sharpe = sample_sharpe(pd.Series(data))
    if sharpe <= benchmark_sharpe:
        return None
    skew = float(pd.Series(data).skew())
    kurtosis = float(pd.Series(data).kurt() + 3)
    z_score = NormalDist().inv_cdf(confidence)
    adjustment = max(1e-12, 1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe**2)
    return float(1 + adjustment * (z_score / (sharpe - benchmark_sharpe)) ** 2)


def sign_flip_test(values: pd.Series, simulations: int, seed: int) -> dict[str, float]:
    """Two-sided randomization test for non-zero mean return."""
    data = _returns(values)
    if len(data) < 2:
        return {"observed_mean": 0.0, "p_value": 1.0}
    generator = np.random.default_rng(seed)
    observed = abs(float(data.mean()))
    exceedances = 0
    for _ in range(simulations):
        signs = generator.choice(np.array([-1.0, 1.0]), size=len(data))
        exceedances += abs(float((data * signs).mean())) >= observed
    return {"observed_mean": float(data.mean()), "p_value": (exceedances + 1) / (simulations + 1)}


def block_bootstrap(
    values: pd.Series,
    *,
    simulations: int,
    block_size: int,
    confidence: float,
    seed: int,
) -> dict[str, Any]:
    """Circular block bootstrap preserving short-range dependence."""
    data = _returns(values)
    if len(data) < 2:
        return {"simulations": 0, "probability_positive": 0.0}
    block_size = min(block_size, len(data))
    generator = np.random.default_rng(seed)
    totals = np.empty(simulations)
    sharpes = np.empty(simulations)
    drawdowns = np.empty(simulations)
    for simulation in range(simulations):
        sampled: list[float] = []
        while len(sampled) < len(data):
            start = int(generator.integers(0, len(data)))
            sampled.extend(
                float(data[(start + offset) % len(data)]) for offset in range(block_size)
            )
        path = np.asarray(sampled[: len(data)], dtype=float)
        totals[simulation] = np.prod(1 + path) - 1
        deviation = float(path.std(ddof=1))
        sharpes[simulation] = float(path.mean() / deviation) if deviation > 0 else 0.0
        drawdowns[simulation] = max_drawdown(pd.Series(path))
    tail = (1 - confidence) / 2
    return {
        "simulations": simulations,
        "block_size": block_size,
        "probability_positive": float((totals > 0).mean()),
        "total_return_median": float(np.median(totals)),
        "total_return_lower": float(np.quantile(totals, tail)),
        "total_return_upper": float(np.quantile(totals, 1 - tail)),
        "periodic_sharpe_lower": float(np.quantile(sharpes, tail)),
        "max_drawdown_lower": float(np.quantile(drawdowns, tail)),
    }
