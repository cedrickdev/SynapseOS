"""Tests for bounded Manager cost attribution."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from core.manager import (
    AgentCostAttributionRequest,
    AgentCostAttributor,
    AttributableCostEvidence,
    CostAttributionSource,
)


def _evidence(
    *,
    project_id: UUID,
    task_id: UUID,
    run_id: UUID,
    agent_id: UUID,
    genome_version_id: UUID,
    source: CostAttributionSource,
    cost: str,
    observed_at: datetime,
    provider_reference: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> AttributableCostEvidence:
    return AttributableCostEvidence(
        evidence_id=uuid4(),
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
        agent_id=agent_id,
        genome_version_id=genome_version_id,
        source=source,
        provider_reference=provider_reference,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=Decimal(cost),
        observed_at=observed_at,
    )


def test_cost_attribution_preserves_bounded_run_breakdown() -> None:
    now = datetime.now(UTC)
    project_id, task_id, run_id, agent_id, genome_version_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    evidence = (
        _evidence(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            source=CostAttributionSource.PROVIDER_CALL,
            provider_reference="provider://primary",
            input_tokens=100,
            output_tokens=40,
            cost="0.02000000",
            observed_at=now,
        ),
        _evidence(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            source=CostAttributionSource.REVIEWER_CALL,
            provider_reference="provider://reviewer",
            input_tokens=20,
            output_tokens=10,
            cost="0.00500000",
            observed_at=now,
        ),
        _evidence(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            source=CostAttributionSource.TOOL_EXECUTION,
            cost="0.00300000",
            observed_at=now,
        ),
        _evidence(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            source=CostAttributionSource.RETRY,
            provider_reference="provider://primary",
            input_tokens=15,
            output_tokens=5,
            cost="0.00400000",
            observed_at=now,
        ),
    )

    result = AgentCostAttributor().attribute(
        AgentCostAttributionRequest(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            evidence=evidence,
            calculated_at=now,
        )
    )

    assert result.input_tokens == 135
    assert result.output_tokens == 55
    assert result.provider_cost == Decimal("0.02500000")
    assert result.tool_cost == Decimal("0.00300000")
    assert result.retry_cost == Decimal("0.00400000")
    assert result.total_cost == Decimal("0.03200000")
    assert result.provider_references == ("provider://primary", "provider://reviewer")
    assert result.provider_call_count == 1
    assert result.reviewer_call_count == 1
    assert result.tool_execution_count == 1
    assert result.retry_count == 1
    assert result.may_spend is False
    assert result.may_assign is False
    assert result.may_mutate_budget is False


def test_cost_attribution_rejects_foreign_evidence() -> None:
    now = datetime.now(UTC)
    project_id, task_id, run_id, agent_id, genome_version_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    foreign = _evidence(
        project_id=uuid4(),
        task_id=task_id,
        run_id=run_id,
        agent_id=agent_id,
        genome_version_id=genome_version_id,
        source=CostAttributionSource.TOOL_EXECUTION,
        cost="0.01000000",
        observed_at=now,
    )
    request = AgentCostAttributionRequest(
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
        agent_id=agent_id,
        genome_version_id=genome_version_id,
        evidence=(foreign,),
        calculated_at=now,
    )

    with pytest.raises(ValueError, match="attribution scope"):
        AgentCostAttributor().attribute(request)


def test_cost_attribution_rejects_future_evidence() -> None:
    now = datetime.now(UTC)
    project_id, task_id, run_id, agent_id, genome_version_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    future = _evidence(
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
        agent_id=agent_id,
        genome_version_id=genome_version_id,
        source=CostAttributionSource.TOOL_EXECUTION,
        cost="0.01000000",
        observed_at=now + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="future"):
        AgentCostAttributor().attribute(
            AgentCostAttributionRequest(
                project_id=project_id,
                task_id=task_id,
                run_id=run_id,
                agent_id=agent_id,
                genome_version_id=genome_version_id,
                evidence=(future,),
                calculated_at=now,
            )
        )


def test_cost_attribution_rejects_duplicate_evidence() -> None:
    now = datetime.now(UTC)
    project_id, task_id, run_id, agent_id, genome_version_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    item = _evidence(
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
        agent_id=agent_id,
        genome_version_id=genome_version_id,
        source=CostAttributionSource.PROVIDER_CALL,
        provider_reference="provider://primary",
        cost="0.01000000",
        observed_at=now,
    )

    with pytest.raises(ValueError, match="unique"):
        AgentCostAttributionRequest(
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            genome_version_id=genome_version_id,
            evidence=(item, item),
            calculated_at=now,
        )
