"""Provider-neutral secure document-ingestion contracts for Phase 25."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import unicodedata
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Protocol, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.intake.errors import IntakeError, IntakeErrorCode
from core.intake.types import IntakeRequest, IntakeResult

_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
_MAX_MARKDOWN_BYTES = 262_144
_MEDIA_TYPES = {
    "application/pdf": (".pdf", "PDF"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx", "DOCX"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (".pptx", "PPTX"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (".xlsx", "XLSX"),
}
_AUTHORITY_WORDS = frozenset({"instruction", "instructions", "policy", "prompt", "system"})
_OVERRIDE_WORDS = frozenset({"bypass", "discard", "disregard", "forget", "ignore", "override"})
_DISCLOSURE_WORDS = frozenset({"expose", "leak", "print", "repeat", "reveal", "show"})


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Filename = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_require_nonblank)]
MediaType = Annotated[str, Field(min_length=1, max_length=127), AfterValidator(_require_nonblank)]


class DocumentFormat(StrEnum):
    """Closed document formats accepted by intake V1."""

    PDF = "PDF"
    DOCX = "DOCX"
    PPTX = "PPTX"
    XLSX = "XLSX"


class DocumentRetentionPolicy(StrEnum):
    """Phase 25 retains no client document content."""

    EPHEMERAL = "EPHEMERAL"


class DocumentSensitivity(StrEnum):
    """Client-declared sensitivity used by the intake disclosure gate."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class _ImmutableDocumentModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ClientDocument(_ImmutableDocumentModel):
    """One bounded client upload with explicit processing consent and retention."""

    project_id: Identifier
    source_id: Identifier
    filename: Filename
    media_type: MediaType
    content: Annotated[bytes, Field(min_length=1, max_length=_MAX_DOCUMENT_BYTES)]
    retention_policy: DocumentRetentionPolicy
    sensitivity: DocumentSensitivity
    provider_processing_approved: bool

    @field_validator("filename")
    @classmethod
    def require_plain_filename(cls, value: str) -> str:
        if (
            PurePosixPath(value).name != value
            or PureWindowsPath(value).name != value
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("filename must not contain a path")
        return value

    @model_validator(mode="after")
    def require_supported_matching_type_and_consent(self) -> Self:
        expected = _MEDIA_TYPES.get(self.media_type)
        suffix = PurePosixPath(self.filename).suffix.lower()
        if expected is None or suffix != expected[0]:
            raise ValueError("document type and filename are unsupported or inconsistent")
        if self.sensitivity is DocumentSensitivity.RESTRICTED:
            raise ValueError("restricted documents cannot be processed in Phase 25")
        if not self.provider_processing_approved:
            raise ValueError("provider processing must be explicitly approved")
        return self


class DocumentConversionRequest(_ImmutableDocumentModel):
    """Canonical request passed to an isolated document converter."""

    document: ClientDocument
    format: DocumentFormat
    max_output_bytes: Annotated[int, Field(gt=0, le=_MAX_MARKDOWN_BYTES)] = _MAX_MARKDOWN_BYTES

    @model_validator(mode="after")
    def require_matching_format(self) -> Self:
        expected = _MEDIA_TYPES[self.document.media_type][1]
        if self.format.value != expected:
            raise ValueError("conversion format does not match document media type")
        return self


class ConvertedDocument(_ImmutableDocumentModel):
    """Bounded Markdown returned by an isolated converter."""

    markdown: Annotated[
        str,
        Field(min_length=1, max_length=_MAX_MARKDOWN_BYTES),
        AfterValidator(_require_nonblank),
    ]

    @model_validator(mode="after")
    def require_bounded_utf8(self) -> Self:
        if len(self.markdown.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
            raise ValueError("converted Markdown exceeds the byte limit")
        return self


class DocumentProvenance(_ImmutableDocumentModel):
    """Content-free provenance retained after ephemeral conversion."""

    source_id: Identifier
    filename: Filename
    media_type: MediaType
    format: DocumentFormat
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    size_bytes: Annotated[int, Field(gt=0, le=_MAX_DOCUMENT_BYTES)]
    retention_policy: DocumentRetentionPolicy
    sensitivity: DocumentSensitivity
    persisted: bool

    @field_validator("persisted")
    @classmethod
    def require_ephemeral_result(cls, value: bool) -> bool:
        if value:
            raise ValueError("Phase 25 document content must not be persisted")
        return value


class DocumentIntakeResult(_ImmutableDocumentModel):
    """Structured intake plus non-sensitive source provenance."""

    intake: IntakeResult
    provenance: DocumentProvenance


class DocumentConverter(Protocol):
    """Injected converter boundary; implementations never own client retention policy."""

    async def convert(self, request: DocumentConversionRequest) -> ConvertedDocument: ...


def document_format(document: ClientDocument) -> DocumentFormat:
    """Resolve the already validated media type to a closed format."""
    return DocumentFormat(_MEDIA_TYPES[document.media_type][1])


def contains_prompt_injection(markdown: str) -> bool:
    """Flag known instruction-override markers as defense in depth, not as an authority boundary."""
    normalized = unicodedata.normalize("NFKC", markdown).casefold()
    normalized = "".join(
        character for character in normalized if unicodedata.category(character) != "Cf"
    )
    tokens = tuple(re.findall(r"[a-z0-9]+", normalized))
    token_set = frozenset(tokens)
    authority_override = bool(token_set & _AUTHORITY_WORDS and token_set & _OVERRIDE_WORDS)
    authority_disclosure = bool(token_set & _AUTHORITY_WORDS and token_set & _DISCLOSURE_WORDS)
    role_forgery = (
        {"im", "start", "system"}.issubset(token_set)
        or {"you", "are", "now", "system"}.issubset(token_set)
        or {"act", "as", "system"}.issubset(token_set)
    )
    indirect_targeting = {"when", "read", "ai"}.issubset(token_set) and bool(
        token_set & (_OVERRIDE_WORDS | _DISCLOSURE_WORDS)
    )
    return authority_override or authority_disclosure or role_forgery or indirect_targeting


async def ingest_document(
    document: ClientDocument,
    *,
    converter: DocumentConverter | None,
    analyze: object,
    timeout_seconds: float,
) -> DocumentIntakeResult:
    """Convert ephemerally, reject unsafe content, and delegate textual analysis once."""
    if converter is None:
        raise IntakeError(IntakeErrorCode.CONVERTER_UNAVAILABLE)
    if not math.isfinite(timeout_seconds) or not 0.0 < timeout_seconds <= 30.0:
        raise ValueError("document conversion timeout must be finite and between 0 and 30")
    request = DocumentConversionRequest(document=document, format=document_format(document))
    try:
        async with asyncio.timeout(timeout_seconds):
            raw_converted = await converter.convert(request)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        raise IntakeError(IntakeErrorCode.CONVERSION_TIMEOUT) from None
    except Exception:
        raise IntakeError(IntakeErrorCode.CONVERSION_FAILURE) from None
    try:
        if type(raw_converted) is not ConvertedDocument:
            raise ValueError("converter returned an invalid result")
        converted = ConvertedDocument.model_validate(
            raw_converted.model_dump(mode="python", warnings=False), strict=True
        )
        if contains_prompt_injection(converted.markdown):
            raise IntakeError(IntakeErrorCode.UNSAFE_DOCUMENT)
        analyzer = analyze
        run = getattr(analyzer, "run", None)
        if not callable(run):
            raise ValueError("intake analyzer is invalid")
        intake = await run(
            IntakeRequest(project_id=document.project_id, specification=converted.markdown)
        )
    except IntakeError:
        raise
    except asyncio.CancelledError:
        raise
    except Exception:
        raise IntakeError(IntakeErrorCode.CONVERSION_FAILURE) from None
    provenance = DocumentProvenance(
        source_id=document.source_id,
        filename=document.filename,
        media_type=document.media_type,
        format=request.format,
        sha256=hashlib.sha256(document.content).hexdigest(),
        size_bytes=len(document.content),
        retention_policy=document.retention_policy,
        sensitivity=document.sensitivity,
        persisted=False,
    )
    return DocumentIntakeResult(intake=intake, provenance=provenance)
