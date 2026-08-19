"""Safe-enough explicit plugin loading for trusted local adapters."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points
from typing import Any

from alphaverdict.data.adapter import DataAdapter
from alphaverdict.exceptions import ConfigurationError


def import_object(reference: str) -> Any:
    """Import ``module:object`` without eval or implicit discovery."""
    module_name, separator, object_name = reference.partition(":")
    if not separator or not module_name or not object_name:
        raise ConfigurationError("plugin references must use module:object syntax")
    module = import_module(module_name)
    try:
        return getattr(module, object_name)
    except AttributeError as exc:
        raise ConfigurationError(f"plugin object not found: {reference}") from exc


def adapter_class(reference: str) -> type[DataAdapter]:
    """Resolve a built-in, entry-point, or explicit adapter class."""
    if ":" in reference:
        candidate = import_object(reference)
    else:
        matches = [
            item
            for item in entry_points(group="alphaverdict.data_adapters")
            if item.name == reference
        ]
        if not matches:
            raise ConfigurationError(f"unknown data adapter: {reference}")
        candidate = matches[0].load()
    if not isinstance(candidate, type):
        raise ConfigurationError(f"data adapter must be a class: {reference}")
    return candidate
