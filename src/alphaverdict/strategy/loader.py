"""Explicit loading of trusted local strategy modules."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from alphaverdict.data.registry import import_object
from alphaverdict.exceptions import ConfigurationError
from alphaverdict.strategy.base import StockStrategy
from alphaverdict.utils import resolve_within, sha256_text


def _module_from_file(path: Path, root: Path) -> ModuleType:
    path_identity = sha256_text(path.as_posix())[:12]
    module_name = f"alphaverdict_user_{path.stem}_{path_identity}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ConfigurationError(f"cannot import strategy file: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    root_text = str(root)
    inserted = root_text not in sys.path
    if inserted:
        sys.path.insert(0, root_text)
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted and root_text in sys.path:
            sys.path.remove(root_text)
    return module


def load_strategy(reference: str, *, root: Path, allow_outside_root: bool = False) -> StockStrategy:
    """Load a trusted ``path.py:object`` or installed ``module:object`` strategy."""
    source, separator, name = reference.partition(":")
    if not separator or not source or not name:
        raise ConfigurationError("strategy references must use path.py:object or module:object")
    if source.endswith(".py") or "/" in source or "\\" in source:
        path = resolve_within(root, source, allow_outside=allow_outside_root)
        if not path.is_file():
            raise ConfigurationError(f"strategy file does not exist: {source}")
        candidate: Any = getattr(_module_from_file(path, root), name, None)
    else:
        candidate = import_object(reference)
    if candidate is None:
        raise ConfigurationError(f"strategy object not found: {reference}")
    if isinstance(candidate, type):
        candidate = candidate()
    if not isinstance(candidate, StockStrategy):
        raise ConfigurationError("strategy object must inherit alphaverdict.StockStrategy")
    return candidate
