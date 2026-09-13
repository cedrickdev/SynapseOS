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
        back_populates="genome_version"
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
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    genome_version: Mapped[AgentGenomeVersion] = relationship(back_populates="capability_metrics")


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
