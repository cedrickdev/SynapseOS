"""PostgreSQL transaction-local enforcement for one workflow deadline."""

from __future__ import annotations

from math import floor
from time import monotonic

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.workflows.errors import (
    WorkflowError,
    WorkflowErrorCode,
    _discard_exception,
)

_TIMEOUT_SQLSTATES = frozenset({"55P03", "57014"})


def _configure_transaction_timeouts(session: Session, deadline: float) -> None:
    """Apply the remaining global budget to the current PostgreSQL transaction."""
    remaining = deadline - monotonic()
    if remaining <= 0.0:
        raise WorkflowError(WorkflowErrorCode.TIMEOUT)
    timeout_milliseconds = max(1, floor(remaining * 1_000.0))
    timeout_setting = f"{timeout_milliseconds}ms"
    try:
        session.execute(
            text(
                "SELECT "
                "set_config('statement_timeout', :timeout_setting, true), "
                "set_config('lock_timeout', :timeout_setting, true)"
            ),
            {"timeout_setting": timeout_setting},
        )
    except SQLAlchemyError as error:
        code = (
            WorkflowErrorCode.TIMEOUT
            if _is_database_timeout(error) or monotonic() >= deadline
            else WorkflowErrorCode.PERSISTENCE_FAILURE
        )
        _discard_exception(error)
        del error
        raise WorkflowError(code) from None
    if monotonic() >= deadline:
        raise WorkflowError(WorkflowErrorCode.TIMEOUT)


def _is_database_timeout(error: BaseException) -> bool:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        sqlstate = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if sqlstate in _TIMEOUT_SQLSTATES:
            return True
        original = getattr(current, "orig", None)
        cause = current.__cause__
        context = current.__context__
        if isinstance(original, BaseException):
            pending.append(original)
        if cause is not None:
            pending.append(cause)
        if context is not None:
            pending.append(context)
    return False
