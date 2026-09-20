"""Deterministic, non-authorizing risk classification for the Autonomy Governor."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from core.enums import ToolRiskLevel


class GovernedActionType(StrEnum):
    """Closed action categories classified before any Governor policy is evaluated."""

    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    COMMAND_EXECUTION = "COMMAND_EXECUTION"
    DATABASE_MIGRATION = "DATABASE_MIGRATION"
    DEPLOYMENT = "DEPLOYMENT"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"
    FINANCIAL_TRANSACTION = "FINANCIAL_TRANSACTION"


class ExecutionEnvironment(StrEnum):
    """Execution environments with increasing operational consequences."""

    LOCAL = "LOCAL"
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"


class RiskSeverity(StrEnum):
    """Closed severity scale for non-tool risk inputs."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Reversibility(StrEnum):
    """Whether a completed action can be safely compensated."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    IRREVERSIBLE = "IRREVERSIBLE"


class RiskLevel(StrEnum):
    """Closed result levels emitted by the deterministic classifier."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskReasonCode(StrEnum):
    """Closed factors explaining a classification result without making an authority decision."""

    ACTION_TYPE = "ACTION_TYPE"
    TOOL_RISK = "TOOL_RISK"
    ENVIRONMENT = "ENVIRONMENT"
    DATA_SENSITIVITY = "DATA_SENSITIVITY"
    BLAST_RADIUS = "BLAST_RADIUS"
    IRREVERSIBILITY = "IRREVERSIBILITY"
    COST = "COST"
    EXTERNAL_SIDE_EFFECTS = "EXTERNAL_SIDE_EFFECTS"
    PRODUCTION_IMPACT = "PRODUCTION_IMPACT"
    PRODUCTION_CRITICAL_ACTION = "PRODUCTION_CRITICAL_ACTION"


class _StrictRiskModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class RiskContext(_StrictRiskModel):
    """All required, bounded inputs for classification of one proposed action."""

    action_type: GovernedActionType
    tool_risk: ToolRiskLevel
    environment: ExecutionEnvironment
    data_sensitivity: RiskSeverity
    blast_radius: RiskSeverity
    reversibility: Reversibility
    cost: RiskSeverity
    external_side_effects: RiskSeverity
    production_impact: RiskSeverity


class RiskAssessment(_StrictRiskModel):
    """A reproducible risk classification, not an authorization or policy decision."""

    score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
    level: RiskLevel
    reason_codes: Annotated[tuple[RiskReasonCode, ...], Field(min_length=1, max_length=10)]
    classifier_version: Annotated[str, Field(min_length=1, max_length=128)]


class RiskClassifier:
    """Conservative pure classifier that never grants or changes authority."""

    VERSION: ClassVar[str] = "governor-risk-v1"

    _ACTION_SCORES: ClassVar[dict[GovernedActionType, Decimal]] = {
        GovernedActionType.READ: Decimal("0.00"),
        GovernedActionType.WRITE: Decimal("0.25"),
        GovernedActionType.DELETE: Decimal("0.50"),
        GovernedActionType.COMMAND_EXECUTION: Decimal("0.50"),
        GovernedActionType.DATABASE_MIGRATION: Decimal("0.75"),
        GovernedActionType.DEPLOYMENT: Decimal("0.75"),
        GovernedActionType.EXTERNAL_SIDE_EFFECT: Decimal("0.75"),
        GovernedActionType.FINANCIAL_TRANSACTION: Decimal("1.00"),
    }
    _TOOL_SCORES: ClassVar[dict[ToolRiskLevel, Decimal]] = {
        ToolRiskLevel.LOW: Decimal("0.25"),
        ToolRiskLevel.MEDIUM: Decimal("0.50"),
        ToolRiskLevel.HIGH: Decimal("0.75"),
        ToolRiskLevel.CRITICAL: Decimal("1.00"),
    }
    _ENVIRONMENT_SCORES: ClassVar[dict[ExecutionEnvironment, Decimal]] = {
        ExecutionEnvironment.LOCAL: Decimal("0.00"),
        ExecutionEnvironment.DEVELOPMENT: Decimal("0.25"),
        ExecutionEnvironment.STAGING: Decimal("0.50"),
        ExecutionEnvironment.PRODUCTION: Decimal("1.00"),
    }
    _SEVERITY_SCORES: ClassVar[dict[RiskSeverity, Decimal]] = {
        RiskSeverity.NONE: Decimal("0.00"),
        RiskSeverity.LOW: Decimal("0.25"),
        RiskSeverity.MEDIUM: Decimal("0.50"),
        RiskSeverity.HIGH: Decimal("0.75"),
        RiskSeverity.CRITICAL: Decimal("1.00"),
    }
    _REVERSIBILITY_SCORES: ClassVar[dict[Reversibility, Decimal]] = {
        Reversibility.FULL: Decimal("0.00"),
        Reversibility.PARTIAL: Decimal("0.50"),
        Reversibility.IRREVERSIBLE: Decimal("1.00"),
    }
    _CRITICAL_PRODUCTION_ACTIONS: ClassVar[frozenset[GovernedActionType]] = frozenset(
        {
            GovernedActionType.DATABASE_MIGRATION,
            GovernedActionType.DEPLOYMENT,
            GovernedActionType.EXTERNAL_SIDE_EFFECT,
            GovernedActionType.FINANCIAL_TRANSACTION,
        }
    )

    def classify(self, context: RiskContext) -> RiskAssessment:
        """Classify one action from closed inputs using the highest applicable risk factor."""
        factors = (
            (RiskReasonCode.ACTION_TYPE, self._ACTION_SCORES[context.action_type]),
            (RiskReasonCode.TOOL_RISK, self._TOOL_SCORES[context.tool_risk]),
            (RiskReasonCode.ENVIRONMENT, self._ENVIRONMENT_SCORES[context.environment]),
            (
                RiskReasonCode.DATA_SENSITIVITY,
                self._SEVERITY_SCORES[context.data_sensitivity],
            ),
            (RiskReasonCode.BLAST_RADIUS, self._SEVERITY_SCORES[context.blast_radius]),
            (RiskReasonCode.IRREVERSIBILITY, self._REVERSIBILITY_SCORES[context.reversibility]),
            (RiskReasonCode.COST, self._SEVERITY_SCORES[context.cost]),
            (
                RiskReasonCode.EXTERNAL_SIDE_EFFECTS,
                self._SEVERITY_SCORES[context.external_side_effects],
            ),
            (
                RiskReasonCode.PRODUCTION_IMPACT,
                self._SEVERITY_SCORES[context.production_impact],
            ),
        )
        score = max(value for _, value in factors)
        reason_codes = tuple(reason for reason, value in factors if value > Decimal("0"))

        if (
            context.environment is ExecutionEnvironment.PRODUCTION
            and context.action_type in self._CRITICAL_PRODUCTION_ACTIONS
        ):
            score = Decimal("1.00")
            reason_codes = (*reason_codes, RiskReasonCode.PRODUCTION_CRITICAL_ACTION)

        return RiskAssessment(
            score=score,
            level=self._level_for(score),
            reason_codes=reason_codes,
            classifier_version=self.VERSION,
        )

    @staticmethod
    def _level_for(score: Decimal) -> RiskLevel:
        if score >= Decimal("1.00"):
            return RiskLevel.CRITICAL
        if score >= Decimal("0.75"):
            return RiskLevel.HIGH
        if score >= Decimal("0.50"):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
