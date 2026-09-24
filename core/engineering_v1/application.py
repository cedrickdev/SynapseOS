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
    ) -> None:
        if not callable(session_factory):
            raise ValueError("session factory must be callable")
        if not callable(getattr(stage_factory, "create", None)):
            raise ValueError("stage suite factory must expose create")
        self._session_factory = session_factory
        self._stage_factory = stage_factory

    async def run(self, request: EngineeringV1Request) -> EngineeringV1Result:
        """Execute exactly once, then commit or roll back and always close."""
        session = self._session_factory()
        if not isinstance(session, Session):
            raise EngineeringV1Error(EngineeringV1ErrorCode.STAGE_FAILURE)
        try:
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
            session.rollback()
            raise
        except EngineeringV1Error:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise EngineeringV1Error(EngineeringV1ErrorCode.STAGE_FAILURE) from None
        finally:
            session.close()
