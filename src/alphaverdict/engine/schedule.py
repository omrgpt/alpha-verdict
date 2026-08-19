"""Trading-session schedules derived from user-supplied stock data."""

from __future__ import annotations

import pandas as pd

from alphaverdict.engine.models import RebalanceFrequency


def decision_dates(
    sessions: pd.DatetimeIndex,
    frequency: RebalanceFrequency,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DatetimeIndex:
    """Select causal decision dates; execution always occurs next session."""
    values = pd.DatetimeIndex(pd.to_datetime(sessions, utc=True)).drop_duplicates().sort_values()
    if start is not None:
        values = values[values >= start]
    if end is not None:
        values = values[values <= end]
    if frequency is RebalanceFrequency.DAILY:
        return values
    frame = pd.DataFrame(index=values)
    period_values = values.tz_localize(None)
    if frequency is RebalanceFrequency.WEEKLY:
        keys = period_values.to_period("W-FRI")
    else:
        keys = period_values.to_period("M")
    return pd.DatetimeIndex(frame.groupby(keys, sort=True).tail(1).index)


def next_session(all_sessions: pd.DatetimeIndex, timestamp: pd.Timestamp) -> pd.Timestamp | None:
    """Find the first available session strictly after a decision timestamp."""
    position = all_sessions.searchsorted(timestamp, side="right")
    return None if position >= len(all_sessions) else pd.Timestamp(all_sessions[position])
