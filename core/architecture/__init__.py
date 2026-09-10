"""Technology-neutral architecture proposal contracts and composition."""

from core.architecture.agent import ArchitectureAgent, CTOAgent
from core.architecture.analysis import ArchitectureAnalyzer
from core.architecture.errors import ArchitectureError, ArchitectureErrorCode
from core.architecture.provider import CancellationSafeLLMProvider
from core.architecture.types import (
    ADRDraft,
    ArchitectureAnalysis,
    ArchitectureOption,
    ArchitectureRequest,
    ArchitectureResult,
    ArchitectureStatus,
    build_architecture_result,
)

__all__ = [
    "ADRDraft",
    "ArchitectureAgent",
    "ArchitectureAnalysis",
    "ArchitectureAnalyzer",
    "ArchitectureError",
    "ArchitectureErrorCode",
    "ArchitectureOption",
    "ArchitectureRequest",
    "ArchitectureResult",
    "ArchitectureStatus",
    "CancellationSafeLLMProvider",
    "CTOAgent",
    "build_architecture_result",
]
