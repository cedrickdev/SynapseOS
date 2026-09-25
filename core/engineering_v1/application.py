"""Transactional application boundary for one Engineering V1 workflow run."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from sqlalchemy.orm import Session

from core.engineering_v1.errors import EngineeringV1Error, EngineeringV1ErrorCode
from core.engineering_v1.orchestrator import EngineeringV1Orchestrator
from core.engineering_v1.ports import EngineeringStageSuiteFactory
from core.engineering_v1.types import EngineeringV1Request, EngineeringV1Result


class EngineeringV1Application:
    """Own one database transaction and stage suite per workflow invocation."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        stage_factory: EngineeringStageSuiteFactory,
        *,
        timeout_seconds: float = 3_600.0,
    ) -> None:
        if not callable(session_factory):
            raise ValueError("session factory must be callable")
        if not callable(getattr(stage_factory, "create", None)):
            raise ValueError("stage suite factory must expose create")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0.0 < float(timeout_seconds) <= 3_600.0
        ):
            raise ValueError("application timeout must be between 0 and 3600 seconds")
        self._session_factory = session_factory
        self._stage_factory = stage_factory
        self._timeout_seconds = float(timeout_seconds)

    async def run(self, request: EngineeringV1Request) -> EngineeringV1Result:
        """Execute exactly once, then commit or roll back and always close."""
        session: Session | None = None
        try:
            if type(request) is not EngineeringV1Request:
                raise EngineeringV1Error(EngineeringV1ErrorCode.INVALID_INPUT)
            if request.timeout_seconds > self._timeout_seconds:
                raise EngineeringV1Error(EngineeringV1ErrorCode.INVALID_INPUT)
            session = self._session_factory()
            if not isinstance(session, Session):
                raise EngineeringV1Error(EngineeringV1ErrorCode.STAGE_FAILURE)
            from infrastructure.engineering_v1.audit import SQLAlchemyEngineeringAuditSink

            suite = self._stage_factory.create(session)
            orchestrator = EngineeringV1Orchestrator(
                suite.ordered_stages(),
                SQLAlchemyEngineeringAuditSink(session),
            )
            result = await orchestrator.run(request)
            session.commit()
            return result
        except asyncio.CancelledError:
            if session is not None:
                session.rollback()
            raise
        except EngineeringV1Error:
            if session is not None:
                session.rollback()
            raise
        except Exception:
            if session is not None:
                session.rollback()
            raise EngineeringV1Error(EngineeringV1ErrorCode.STAGE_FAILURE) from None
        finally:
            if session is not None:
                session.close()
