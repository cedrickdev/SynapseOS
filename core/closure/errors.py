"""Sanitized failures for project closure."""

from __future__ import annotations


class ProjectClosureError(ValueError):
    """Raised when a project cannot be closed safely."""
