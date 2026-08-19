"""Typed exceptions raised by AlphaVerdict."""


class AlphaVerdictError(Exception):
    """Base class for expected AlphaVerdict errors."""


class ConfigurationError(AlphaVerdictError):
    """Raised when a project configuration is invalid or unsafe."""


class DataContractError(AlphaVerdictError):
    """Raised when provider data violates the canonical contract."""


class StrategyContractError(AlphaVerdictError):
    """Raised when a strategy returns malformed or non-deterministic signals."""


class InsufficientDataError(AlphaVerdictError):
    """Raised when a requested evaluation cannot be supported by available data."""


class SecurityBoundaryError(AlphaVerdictError):
    """Raised when a path or plugin crosses a configured trust boundary."""
