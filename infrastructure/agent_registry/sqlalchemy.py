"""Bounded read-only SQLAlchemy agent registry source."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.agent_registry import AgentCandidate, AgentCapabilitySnapshot
from core.enums import Permission
from infrastructure.database.models import Agent, AgentCapability, AgentPermission

_MAX_CANDIDATES = 100
_MAX_CAPABILITIES_PER_AGENT = 64
_MAX_PERMISSIONS_PER_AGENT = 64


class AgentRegistryUnavailableError(RuntimeError):
    """Sanitized registry persistence failure."""

    def __init__(self) -> None:
        super().__init__("Agent registry is unavailable.")


class SQLAlchemyAgentRegistrySource:
    """Project active capabilities and grants without mutating the session."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._clock = clock

    def list_candidates(
        self,
        *,
        project_id: uuid.UUID,
        limit: int,
    ) -> tuple[AgentCandidate, ...]:
        if type(project_id) is not uuid.UUID:
            raise ValueError("project_id must be a UUID")
        if type(limit) is not int or not 1 <= limit <= _MAX_CANDIDATES:
            raise ValueError("registry limit must be between 1 and 100")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("registry clock must return an aware datetime")
        try:
            with self._session.no_autoflush:
                agents = tuple(self._session.scalars(_agent_query(limit)))
                if not agents:
                    return ()
                agent_ids = tuple(agent.id for agent in agents)
                capabilities = tuple(
                    self._session.scalars(_capability_query(agent_ids, len(agent_ids)))
                )
                permissions = tuple(
                    self._session.scalars(
                        _permission_query(agent_ids, project_id, now, len(agent_ids))
                    )
                )
        except SQLAlchemyError:
            raise AgentRegistryUnavailableError() from None
        _require_bounded_relations(capabilities, permissions, len(agents))
        return _build_candidates(agents, capabilities, permissions)


def _agent_query(limit: int) -> Select[tuple[Agent]]:
    return select(Agent).order_by(Agent.id).limit(limit)


def _capability_query(
    agent_ids: tuple[uuid.UUID, ...],
    agent_count: int,
) -> Select[tuple[AgentCapability]]:
    return (
        select(AgentCapability)
        .where(AgentCapability.agent_id.in_(agent_ids), AgentCapability.active.is_(True))
        .order_by(AgentCapability.agent_id, AgentCapability.capability)
        .limit(agent_count * _MAX_CAPABILITIES_PER_AGENT + 1)
    )


def _permission_query(
    agent_ids: tuple[uuid.UUID, ...],
    project_id: uuid.UUID,
    now: datetime,
    agent_count: int,
) -> Select[tuple[AgentPermission]]:
    return (
        select(AgentPermission)
        .where(
            AgentPermission.agent_id.in_(agent_ids),
            or_(AgentPermission.project_id.is_(None), AgentPermission.project_id == project_id),
            AgentPermission.revoked_at.is_(None),
            or_(AgentPermission.expires_at.is_(None), AgentPermission.expires_at > now),
        )
        .order_by(AgentPermission.agent_id, AgentPermission.permission)
        .limit(agent_count * _MAX_PERMISSIONS_PER_AGENT + 1)
    )


def _require_bounded_relations(
    capabilities: tuple[AgentCapability, ...],
    permissions: tuple[AgentPermission, ...],
    agent_count: int,
) -> None:
    if len(capabilities) > agent_count * _MAX_CAPABILITIES_PER_AGENT:
        raise AgentRegistryUnavailableError()
    if len(permissions) > agent_count * _MAX_PERMISSIONS_PER_AGENT:
        raise AgentRegistryUnavailableError()
    capability_counts: dict[uuid.UUID, int] = defaultdict(int)
    permission_counts: dict[uuid.UUID, int] = defaultdict(int)
    for capability in capabilities:
        capability_counts[capability.agent_id] += 1
    for permission in permissions:
        permission_counts[permission.agent_id] += 1
    if any(count > _MAX_CAPABILITIES_PER_AGENT for count in capability_counts.values()):
        raise AgentRegistryUnavailableError()
    if any(count > _MAX_PERMISSIONS_PER_AGENT for count in permission_counts.values()):
        raise AgentRegistryUnavailableError()


def _build_candidates(
    agents: tuple[Agent, ...],
    capabilities: tuple[AgentCapability, ...],
    permissions: tuple[AgentPermission, ...],
) -> tuple[AgentCandidate, ...]:
    capabilities_by_agent: dict[uuid.UUID, list[AgentCapabilitySnapshot]] = defaultdict(list)
    permissions_by_agent: dict[uuid.UUID, set[Permission]] = defaultdict(set)
    for capability in capabilities:
        capabilities_by_agent[capability.agent_id].append(
            AgentCapabilitySnapshot(
                name=capability.capability,
                expertise=capability.expertise_score,
            )
        )
    for permission in permissions:
        permissions_by_agent[permission.agent_id].add(permission.permission)
    return tuple(
        AgentCandidate(
            agent_id=agent.id,
            slug=agent.slug,
            seniority=agent.seniority,
            status=agent.status,
            autonomy_level=agent.autonomy_level,
            reputation=agent.reputation_score,
            reliability=agent.reliability_score,
            capabilities=tuple(capabilities_by_agent[agent.id]),
            active_permissions=tuple(
                sorted(permissions_by_agent[agent.id], key=lambda permission: permission.value)
            ),
        )
        for agent in agents
    )
