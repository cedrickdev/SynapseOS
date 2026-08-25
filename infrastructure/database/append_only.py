"""Global SQLAlchemy guard for application-level append-only entities."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session


class AppendOnlyViolationError(RuntimeError):
    """Raised when persisted append-only history is changed or deleted."""


class AppendOnlyMixin:
    """Marker for ORM entities whose persisted rows are immutable."""


def _reject_append_only_changes(session: Session, _flush_context: Any, _instances: Any) -> None:
    for entity in session.deleted:
        if isinstance(entity, AppendOnlyMixin):
            entity_id = getattr(entity, "id", "<pending>")
            raise AppendOnlyViolationError(
                f"Cannot delete append-only {type(entity).__name__} entity {entity_id}."
            )

    for entity in session.dirty:
        if isinstance(entity, AppendOnlyMixin) and entity not in session.new:
            entity_id = getattr(entity, "id", "<pending>")
            raise AppendOnlyViolationError(
                f"Cannot update append-only {type(entity).__name__} entity {entity_id}."
            )


def register_append_only_guard() -> None:
    """Register the process-wide guard exactly once for all SQLAlchemy sessions."""
    if not event.contains(Session, "before_flush", _reject_append_only_changes):
        event.listen(Session, "before_flush", _reject_append_only_changes)
