"""Bounded project intake contracts and agent composition."""

from core.intake.agent import IntakeAgent, ProjectManagerAgent
from core.intake.analysis import IntakeAnalyzer
from core.intake.documents import (
    ClientDocument,
    ConvertedDocument,
    DocumentConversionRequest,
    DocumentConverter,
    DocumentFormat,
    DocumentIntakeResult,
    DocumentProvenance,
    DocumentRetentionPolicy,
    DocumentSensitivity,
)
from core.intake.errors import IntakeError, IntakeErrorCode
from core.intake.types import (
    IntakeAnalysis,
    IntakeQuestion,
    IntakeQuestionClass,
    IntakeReadiness,
    IntakeRequest,
    IntakeResult,
    build_intake_result,
)

__all__ = [
    "IntakeAgent",
    "IntakeAnalysis",
    "IntakeAnalyzer",
    "IntakeError",
    "IntakeErrorCode",
    "IntakeQuestion",
    "IntakeQuestionClass",
    "IntakeReadiness",
    "IntakeRequest",
    "IntakeResult",
    "ProjectManagerAgent",
    "ClientDocument",
    "ConvertedDocument",
    "DocumentConversionRequest",
    "DocumentConverter",
    "DocumentFormat",
    "DocumentIntakeResult",
    "DocumentProvenance",
    "DocumentRetentionPolicy",
    "DocumentSensitivity",
    "build_intake_result",
]
