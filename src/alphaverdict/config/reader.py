"""Safe YAML reader with unknown-key rejection."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar, cast

import yaml

from alphaverdict.audit.models import AuditConfig
from alphaverdict.config.models import (
    DataConfig,
    ProjectConfig,
    ScreenConfig,
    data_request_from_dict,
)
from alphaverdict.engine.models import BacktestConfig
from alphaverdict.exceptions import ConfigurationError

T = TypeVar("T")


def _mapping(value: Any, section: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigurationError(f"{section} must be a YAML mapping")
    return dict(value)


def _strict(values: dict[str, Any], allowed: set[str], section: str) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ConfigurationError(f"unknown {section} keys: {', '.join(unknown)}")


def _dataclass_values(cls: type[T], raw: Any, section: str) -> T:
    values = _mapping(raw, section)
    allowed = {item.name for item in fields(cast("Any", cls))}
    _strict(values, allowed, section)
    try:
        return cls(**values)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid {section}: {exc}") from exc


def load_project(path: str | Path) -> ProjectConfig:
    """Load a versioned project file without interpolation or object constructors."""
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigurationError(f"configuration file does not exist: {config_path}")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML: {exc}") from exc
    raw = _mapping(loaded, "root")
    allowed = {
        "version",
        "data",
        "strategy",
        "request",
        "screen",
        "backtest",
        "audit",
        "output_dir",
        "allow_outside_root",
    }
    _strict(raw, allowed, "root")
    if raw.get("version", 1) != 1:
        raise ConfigurationError("only configuration version 1 is supported")

    data_values = _mapping(raw.get("data"), "data")
    _strict(data_values, {"adapter", "options"}, "data")
    adapter = data_values.get("adapter")
    if not isinstance(adapter, str) or not adapter.strip():
        raise ConfigurationError("data.adapter is required")
    options = _mapping(data_values.get("options"), "data.options")
    strategy = raw.get("strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        raise ConfigurationError("strategy is required")
    request_values = _mapping(raw.get("request"), "request")
    _strict(request_values, {"start", "end", "symbols", "kinds"}, "request")
    allow_outside_root = raw.get("allow_outside_root", False)
    if not isinstance(allow_outside_root, bool):
        raise ConfigurationError("allow_outside_root must be true or false")
    try:
        return ProjectConfig(
            root=config_path.parent,
            data=DataConfig(adapter.strip(), options),
            strategy=strategy.strip(),
            request=data_request_from_dict(request_values),
            screen=_dataclass_values(ScreenConfig, raw.get("screen"), "screen"),
            backtest=_dataclass_values(BacktestConfig, raw.get("backtest"), "backtest"),
            audit=_dataclass_values(AuditConfig, raw.get("audit"), "audit"),
            output_dir=str(raw.get("output_dir", "runs")),
            allow_outside_root=allow_outside_root,
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid project configuration: {exc}") from exc
