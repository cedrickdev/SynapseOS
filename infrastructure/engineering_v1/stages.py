"""Fresh per-run Engineering V1 stage-suite infrastructure."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageRunner,
    EngineeringStageSuite,
)
from infrastructure.engineering_v1.context import EngineeringRunSnapshot


@dataclass(slots=True)
class EngineeringRunState:
    """Ephemeral values shared only by stages in one workflow invocation."""

    snapshot: EngineeringRunSnapshot | None = None
    results: dict[EngineeringStage, object] = field(default_factory=dict, repr=False)


EngineeringStageBuilder = Callable[
    [Session, EngineeringRunState],
    Sequence[EngineeringStageRunner],
]


class ProductionEngineeringStageSuite(EngineeringStageSuite):
    """Retain one exact stage order and one non-shared ephemeral state."""

    def __init__(
        self,
        stages: Sequence[EngineeringStageRunner],
        run_state: EngineeringRunState,
    ) -> None:
        retained = tuple(stages)
        if tuple(getattr(stage, "stage", None) for stage in retained) != (
            ENGINEERING_V1_STAGE_ORDER
        ):
            raise ValueError("stages must use the exact Engineering V1 stage order")
        self._stages = retained
        self.run_state = run_state

    def ordered_stages(self) -> tuple[EngineeringStageRunner, ...]:
        return self._stages


class ProductionEngineeringStageSuiteFactory:
    """Create a fresh mutable run state before building concrete stages."""

    def __init__(self, builder: EngineeringStageBuilder) -> None:
        if not callable(builder):
            raise ValueError("stage builder must be callable")
        self._builder = builder

    def create(self, session: Session) -> ProductionEngineeringStageSuite:
        state = EngineeringRunState()
        return ProductionEngineeringStageSuite(self._builder(session, state), state)
