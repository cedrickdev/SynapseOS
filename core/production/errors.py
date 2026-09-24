"""Sanitized production composition errors."""

from __future__ import annotations


class ProductionConfigurationError(ValueError):
    """Raised when production configuration cannot be trusted."""

    def __init__(self) -> None:
        super().__init__("Production configuration is invalid.")
