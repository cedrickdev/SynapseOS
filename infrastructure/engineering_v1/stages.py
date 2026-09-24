"""Fresh per-run Engineering V1 stage-suite infrastructure."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from sqlalchemy.orm import Session

from core.engineering_v1 import (
    ENGINEERING_V1_STAGE_ORDER,
    EngineeringStage,
    EngineeringStageEvidence,
    EngineeringStageRunner,
    EngineeringStageSuite,
    EngineeringV1Request,
)
from infrastructure.engineering_v1.context import EngineeringRunSnapshot


@dataclass(slots=True)
class EngineeringRunState:
    """Ephemeral values shared only by stages in one workflow invocation."""

    snapshot: EngineeringRunSnapshot | None = None
    results: dict[EngineeringStage, object] = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class ProductionStageOutcome:
    """Private bounded result retained only inside one Engineering V1 run."""

    passed: bool
    evidence_ids: tuple[str, ...]
    payload: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.passed) is not bool:
            raise TypeError("stage outcome passed flag must be boolean")
        if not isinstance(self.evidence_ids, tuple):
            raise TypeError("stage outcome evidence IDs must be a tuple")


ProductionStageOperation = Callable[
    [
        EngineeringV1Request,
        tuple[EngineeringStageEvidence, ...],
        Session,
        EngineeringRunState,
    ],
    Awaitable[ProductionStageOutcome],
]


@dataclass(frozen=True, slots=True)
class ProductionStageOperations:
    """Require one concrete operation for every Engineering V1 stage."""

    specification_analysis: ProductionStageOperation
    blocking_questions: ProductionStageOperation
    architecture: ProductionStageOperation
    task_planning: ProductionStageOperation
    agent_assignment: ProductionStageOperation
    repository_inspection: ProductionStageOperation
    code_change: ProductionStageOperation
    test_execution: ProductionStageOperation
    independent_review: ProductionStageOperation
    qa: ProductionStageOperation
    security: ProductionStageOperation
    merge_gate: ProductionStageOperation
    audit: ProductionStageOperation
    scoring: ProductionStageOperation
    memory: ProductionStageOperation
    feedback: ProductionStageOperation
    closure: ProductionStageOperation

    def for_stage(self, stage: EngineeringStage) -> ProductionStageOperation:
        operation = cast(ProductionStageOperation, getattr(self, stage.value.casefold()))
        if not callable(operation):
            raise TypeError("every production stage operation must be callable")
        return operation


@dataclass(frozen=True, slots=True)
class ProductionStageAdapter:
    """Execute and cache one required production operation for one run."""

    stage: EngineeringStage
    operation: ProductionStageOperation
    session: Session
    state: EngineeringRunState

    async def run(
        self,
        request: EngineeringV1Request,
        completed: tuple[EngineeringStageEvidence, ...],
    ) -> EngineeringStageEvidence:
        cached = self.state.results.get(self.stage)
        if cached is None:
            cached = await self.operation(request, completed, self.session, self.state)
            if type(cached) is not ProductionStageOutcome:
                raise TypeError("production stage operation returned an invalid result")
            self.state.results[self.stage] = cached
        if type(cached) is not ProductionStageOutcome:
            raise TypeError("production stage cache contains an invalid result")
        return EngineeringStageEvidence(
            stage=self.stage,
            passed=cached.passed,
            evidence_ids=cached.evidence_ids,
        )


def build_production_stages(
    session: Session,
    state: EngineeringRunState,
    operations: ProductionStageOperations,
) -> tuple[EngineeringStageRunner, ...]:
    """Build every ordered adapter without installing a permissive fallback."""
    from infrastructure.engineering_v1.completion_stages import build_completion_stages
    from infrastructure.engineering_v1.delivery_stages import build_delivery_stages
    from infrastructure.engineering_v1.planning_stages import build_planning_stages

    stages = (
        *build_planning_stages(session, state, operations),
        *build_delivery_stages(session, state, operations),
        *build_completion_stages(session, state, operations),
    )
    if tuple(item.stage for item in stages) != ENGINEERING_V1_STAGE_ORDER:
        raise ValueError("production stages must match the exact Engineering V1 order")
    return stages


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
