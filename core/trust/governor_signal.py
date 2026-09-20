"""Non-authorizing Trust signals for a future Autonomy Governor."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.trust.critical_events import (
    CriticalTrustDisposition,
    CriticalTrustEventResult,
)
from core.trust.scoring import TrustOverallScore
from core.trust.types import TrustClass


class TrustGovernorSignalDisposition(StrEnum):
    """Trust's bounded recommendation to the Autonomy Governor."""

    NEUTRAL = "NEUTRAL"
    RESTRICTION_RECOMMENDED = "RESTRICTION_RECOMMENDED"


class _StrictTrustGovernorSignalModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class TrustGovernorSignal(_StrictTrustGovernorSignalModel):
    """Trust evidence for Governor evaluation; never a permission or autonomy grant."""

    overall_score: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]
    trust_class: TrustClass
    trust_algorithm_version: Annotated[str, Field(min_length=1, max_length=128)]
    disposition: TrustGovernorSignalDisposition
    requires_governor_recomputation: bool
    critical_event_id: UUID | None
    may_expand_authority: Literal[False] = False


class TrustGovernorSignalBuilder:
    """Translate Trust results into evidence for, never decisions by, the Governor."""

    def build(
        self,
        overall_score: TrustOverallScore,
        *,
        critical_result: CriticalTrustEventResult | None = None,
    ) -> TrustGovernorSignal:
        if type(overall_score) is not TrustOverallScore:
            raise TypeError("Trust overall score must be canonical")
        if critical_result is not None and type(critical_result) is not CriticalTrustEventResult:
            raise TypeError("critical Trust result must be canonical")
        restricted = (
            critical_result is not None
            and critical_result.disposition is CriticalTrustDisposition.RECOMMEND_RESTRICTION
        )
        return TrustGovernorSignal(
            overall_score=overall_score.overall_score,
            trust_class=overall_score.trust_class,
            trust_algorithm_version=overall_score.algorithm_version,
            disposition=(
                TrustGovernorSignalDisposition.RESTRICTION_RECOMMENDED
                if restricted
                else TrustGovernorSignalDisposition.NEUTRAL
            ),
            requires_governor_recomputation=restricted,
            critical_event_id=(
                critical_result.event_id if restricted and critical_result is not None else None
            ),
        )
