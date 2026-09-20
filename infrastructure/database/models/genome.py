"""Versioned, evidence-ready Agent Genome persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.genome import (
    CapabilityScoringPolicy,
    EvidenceOutcome,
    EvidenceSignal,
    EvidenceSourceType,
    EvidenceUnit,
    GenomeCreationSource,
    GenomeFailureSeverity,
    GenomeMetricWindow,
    GenomeVersionStatus,
)
from infrastructure.database.append_only import AppendOnlyMixin
from infrastructure.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from infrastructure.database.models.organization import Agent


class AgentGenome(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One mutable pointer to an agent's immutable Genome history."""

    __tablename__ = "agent_genomes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["agent_genome_versions.agent_genome_id", "agent_genome_versions.id"],
            name="fk_agent_genomes_current_version_owner",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint("id", "agent_id", name="uq_agent_genomes_id_agent"),
        Index("uq_agent_genomes_agent_id", "agent_id", unique=True),
        Index("ix_agent_genomes_current_version_id", "current_version_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="genome")
    versions: Mapped[list[AgentGenomeVersion]] = relationship(
        back_populates="genome", foreign_keys="AgentGenomeVersion.agent_genome_id"
    )
    current_version: Mapped[AgentGenomeVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class AgentGenomeVersion(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable version of one agent Genome."""

    __tablename__ = "agent_genome_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_nonblank"),
        Index("uq_agent_genome_versions_genome_version", "agent_genome_id", "version", unique=True),
        Index("ix_agent_genome_versions_genome_created", "agent_genome_id", "created_at"),
        UniqueConstraint("agent_genome_id", "id", name="uq_agent_genome_versions_owner_id"),
    )

    agent_genome_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_genomes.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[GenomeVersionStatus] = mapped_column(
        Enum(GenomeVersionStatus, name="genome_version_status"), nullable=False
    )
    created_by: Mapped[GenomeCreationSource] = mapped_column(
        Enum(GenomeCreationSource, name="genome_creation_source"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    genome: Mapped[AgentGenome] = relationship(
        back_populates="versions", foreign_keys=[agent_genome_id]
    )
    capability_metrics: Mapped[list[AgentCapabilityMetric]] = relationship(
        back_populates="genome_version", foreign_keys="AgentCapabilityMetric.genome_version_id"
    )
    performance_metrics: Mapped[list[AgentPerformanceMetric]] = relationship(
        back_populates="genome_version"
    )


class AgentCapabilityMetric(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "agent_capability_metrics"
    __table_args__ = (
        CheckConstraint(
            "capability_key ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'", name="capability_key_identifier"
        ),
        CheckConstraint("score BETWEEN 0 AND 1", name="score_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint(
            "sample_count >= 0 AND success_count >= 0 AND failure_count >= 0",
            name="counts_nonnegative",
        ),
        CheckConstraint(
            "success_count + failure_count = sample_count", name="counts_match_samples"
        ),
        CheckConstraint(
            "(scoring_policy IS NULL AND total_weight IS NULL "
            "AND agent_genome_id IS NULL AND agent_id IS NULL) OR "
            "(scoring_policy IS NOT NULL AND total_weight BETWEEN 1 AND 768 "
            "AND agent_genome_id IS NOT NULL AND agent_id IS NOT NULL)",
            name="scoring_provenance_pair",
        ),
        ForeignKeyConstraint(
            ["agent_genome_id", "genome_version_id"],
            ["agent_genome_versions.agent_genome_id", "agent_genome_versions.id"],
            name="fk_agent_capability_metrics_version_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_genome_id", "agent_id"],
            ["agent_genomes.id", "agent_genomes.agent_id"],
            name="fk_agent_capability_metrics_genome_agent",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "agent_id", name="uq_agent_capability_metrics_id_agent"),
        Index(
            "uq_agent_capability_metrics_version_key",
            "genome_version_id",
            "capability_key",
            unique=True,
        ),
        Index("ix_agent_capability_metrics_key_score", "capability_key", "score"),
    )

    genome_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_genome_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_genome_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scoring_policy: Mapped[CapabilityScoringPolicy | None] = mapped_column(
        Enum(CapabilityScoringPolicy, name="capability_scoring_policy"), nullable=True
    )
    total_weight: Mapped[int | None] = mapped_column(Integer, nullable=True)

    genome_version: Mapped[AgentGenomeVersion] = relationship(
        back_populates="capability_metrics", foreign_keys=[genome_version_id]
    )
    evidence_links: Mapped[list[AgentCapabilityMetricEvidence]] = relationship(
        back_populates="metric", foreign_keys="AgentCapabilityMetricEvidence.metric_id"
    )


class AgentPerformanceMetric(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "agent_performance_metrics"
    __table_args__ = (
        CheckConstraint(
            "metric_name ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'", name="metric_name_identifier"
        ),
        CheckConstraint("sample_count >= 0", name="sample_count_nonnegative"),
        Index(
            "uq_agent_performance_metrics_version_name_window",
            "genome_version_id",
            "metric_name",
            "window",
            unique=True,
        ),
        Index("ix_agent_performance_metrics_name_computed", "metric_name", "computed_at"),
    )

    genome_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_genome_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window: Mapped[GenomeMetricWindow] = mapped_column(
        Enum(GenomeMetricWindow, name="genome_metric_window"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    genome_version: Mapped[AgentGenomeVersion] = relationship(back_populates="performance_metrics")


class AgentFailurePattern(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "agent_failure_patterns"
    __table_args__ = (
        CheckConstraint(
            "pattern_key ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'", name="pattern_key_identifier"
        ),
        CheckConstraint("count > 0", name="positive_count"),
        Index(
            "ix_agent_failure_patterns_agent_key_created", "agent_id", "pattern_key", "created_at"
        ),
        Index("ix_agent_failure_patterns_severity_created", "severity", "created_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[GenomeFailureSeverity] = mapped_column(
        Enum(GenomeFailureSeverity, name="genome_failure_severity"), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", MutableDict.as_mutable(JSONB), default=dict, nullable=False
    )

    agent: Mapped[Agent] = relationship()


class AgentGenomeEvidence(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable, provenance-bound observation used by future Genome calculations."""

    __tablename__ = "agent_genome_evidence"
    __table_args__ = (
        CheckConstraint("task_id IS NULL OR project_id IS NOT NULL", name="task_requires_project"),
        CheckConstraint("(numeric_value IS NULL) = (unit IS NULL)", name="numeric_value_unit_pair"),
        CheckConstraint(
            "numeric_value IS NULL OR numeric_value >= 0", name="numeric_value_nonnegative"
        ),
        CheckConstraint(
            "source_type <> 'AGENT_RUN' OR (run_id IS NOT NULL AND run_id = source_id)",
            name="agent_run_source_binding",
        ),
        CheckConstraint(
            "(source_type = 'AGENT_RUN' AND signal = 'RUN_OUTCOME') OR "
            "(source_type = 'PULL_REQUEST_REVIEW' AND signal = 'REVIEW_OUTCOME') OR "
            "(source_type = 'QA_APPROVAL' AND signal = 'QA_OUTCOME') OR "
            "(source_type = 'SECURITY_APPROVAL' AND signal = 'SECURITY_OUTCOME') OR "
            "(source_type = 'USAGE_RECORD' AND signal IN "
            "('TOTAL_TOKENS', 'WALL_CLOCK_DURATION', 'TOOL_CALL_COUNT', "
            "'CPU_DURATION', 'GPU_DURATION', 'PROVIDER_COST'))",
            name="source_signal_match",
        ),
        CheckConstraint(
            "(source_type = 'AGENT_RUN' AND outcome IN "
            "('SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT') AND numeric_value IS NULL) OR "
            "(source_type = 'PULL_REQUEST_REVIEW' AND outcome IN "
            "('APPROVED', 'CHANGES_REQUESTED') AND numeric_value IS NULL) OR "
            "(source_type IN ('QA_APPROVAL', 'SECURITY_APPROVAL') AND outcome IN "
            "('PASSED', 'REJECTED', 'BLOCKED') AND numeric_value IS NULL) OR "
            "(source_type = 'USAGE_RECORD' AND outcome = 'OBSERVED' "
            "AND numeric_value IS NOT NULL)",
            name="source_outcome_value_match",
        ),
        CheckConstraint(
            "source_type <> 'USAGE_RECORD' OR "
            "(signal = 'TOTAL_TOKENS' AND unit = 'TOKENS' "
            "AND numeric_value = trunc(numeric_value)) OR "
            "(signal = 'TOOL_CALL_COUNT' AND unit = 'COUNT' "
            "AND numeric_value = trunc(numeric_value)) OR "
            "(signal IN ('WALL_CLOCK_DURATION', 'CPU_DURATION', 'GPU_DURATION') "
            "AND unit = 'MILLISECONDS') OR "
            "(signal = 'PROVIDER_COST' AND unit = 'PROVIDER_CURRENCY')",
            name="numeric_signal_unit_match",
        ),
        ForeignKeyConstraint(
            ["project_id", "task_id"],
            ["tasks.project_id", "tasks.id"],
            name="fk_agent_genome_evidence_task_project_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "source_type",
            "source_id",
            "signal",
            name="uq_agent_genome_evidence_source_signal",
        ),
        UniqueConstraint("id", "agent_id", name="uq_agent_genome_evidence_id_agent"),
        Index("ix_agent_genome_evidence_agent_observed", "agent_id", "observed_at"),
        Index("ix_agent_genome_evidence_project_observed", "project_id", "observed_at"),
        Index("ix_agent_genome_evidence_task_observed", "task_id", "observed_at"),
        Index("ix_agent_genome_evidence_signal_observed", "signal", "observed_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=True
    )
    source_type: Mapped[EvidenceSourceType] = mapped_column(
        Enum(EvidenceSourceType, name="genome_evidence_source_type"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    signal: Mapped[EvidenceSignal] = mapped_column(
        Enum(EvidenceSignal, name="genome_evidence_signal"), nullable=False
    )
    outcome: Mapped[EvidenceOutcome] = mapped_column(
        Enum(EvidenceOutcome, name="genome_evidence_outcome"), nullable=False
    )
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    unit: Mapped[EvidenceUnit | None] = mapped_column(
        Enum(EvidenceUnit, name="genome_evidence_unit"), nullable=True
    )
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", MutableDict.as_mutable(JSONB), default=dict, nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capability_metric_links: Mapped[list[AgentCapabilityMetricEvidence]] = relationship(
        back_populates="evidence", foreign_keys="AgentCapabilityMetricEvidence.evidence_id"
    )


class AgentCapabilityMetricEvidence(AppendOnlyMixin, UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable attribution of one evidence row to one calculated capability metric."""

    __tablename__ = "agent_capability_metric_evidence"
    __table_args__ = (
        CheckConstraint("weight BETWEEN 1 AND 3", name="weight_range"),
        CheckConstraint("contribution IN (0, 1)", name="contribution_binary"),
        ForeignKeyConstraint(
            ["metric_id", "agent_id"],
            ["agent_capability_metrics.id", "agent_capability_metrics.agent_id"],
            name="fk_agent_capability_metric_evidence_metric_agent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "agent_id"],
            ["agent_genome_evidence.id", "agent_genome_evidence.agent_id"],
            name="fk_agent_capability_metric_evidence_evidence_agent",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "metric_id", "evidence_id", name="uq_agent_capability_metric_evidence_pair"
        ),
        Index("ix_agent_capability_metric_evidence_evidence", "evidence_id", "metric_id"),
    )

    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_capability_metrics.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_genome_evidence.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    contribution: Mapped[int] = mapped_column(Integer, nullable=False)

    metric: Mapped[AgentCapabilityMetric] = relationship(
        back_populates="evidence_links", foreign_keys=[metric_id]
    )
    evidence: Mapped[AgentGenomeEvidence] = relationship(
        back_populates="capability_metric_links", foreign_keys=[evidence_id]
    )
