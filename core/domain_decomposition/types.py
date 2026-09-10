"""Immutable Phase 27 domain-workstream contracts."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from core.architecture import ArchitectureResult
from core.intake import IntakeResult


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
Text255 = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_require_nonblank)]
Text2048 = Annotated[str, Field(min_length=1, max_length=2_048), AfterValidator(_require_nonblank)]
Text8192 = Annotated[str, Field(min_length=1, max_length=8_192), AfterValidator(_require_nonblank)]
_TECHNICAL_SCOPE_TERMS = frozenset(
    {
        "component",
        "components",
        "controller",
        "controllers",
        "endpoint",
        "endpoints",
        "file",
        "files",
        "page",
        "pages",
    }
)
_FILE_SUFFIXES = (
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".sql",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
)
_MAX_WORKSTREAMS_PER_DOMAIN = 4


def _canonical_workstream_id(name: str) -> str:
    identifier = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return identifier[:128].rstrip("-")


def _has_technical_granularity(value: str) -> bool:
    normalized = value.casefold().strip()
    terms = frozenset(re.findall(r"[a-z]+", normalized))
    return (
        "/" in normalized
        or "\\" in normalized
        or normalized.endswith(_FILE_SUFFIXES)
        or bool(terms & _TECHNICAL_SCOPE_TERMS)
    )


class WorkstreamScope(StrEnum):
    """Allowed business granularity for a temporary workstream."""

    DOMAIN = "DOMAIN"
    SERVICE = "SERVICE"


class _ImmutableDomainModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class DomainDecompositionRequest(_ImmutableDomainModel):
    """Verified requirements and architecture consumed by Phase 27."""

    project_id: Identifier
    intake: IntakeResult
    architecture: ArchitectureResult


class DomainWorkstream(_ImmutableDomainModel):
    """Temporary business workstream proposal without agents or assignments."""

    id: Identifier
    name: Text255
    scope_kind: WorkstreamScope
    purpose: Text2048
    source_domains: Annotated[tuple[Text255, ...], Field(min_length=1, max_length=8)]
    responsibilities: Annotated[tuple[Text2048, ...], Field(min_length=1, max_length=16)]
    required_capabilities: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=32)]
    dependencies: Annotated[tuple[Identifier, ...], Field(max_length=16)]

    @field_validator(
        "responsibilities",
        "source_domains",
        "required_capabilities",
        "dependencies",
        mode="before",
    )
    @classmethod
    def copy_sequences(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_unique_members(self) -> Self:
        if self.id != _canonical_workstream_id(self.name):
            raise ValueError("workstream ID must be derived from its canonical name")
        semantic_values = (self.name, self.purpose, *self.responsibilities)
        if any(_has_technical_granularity(value) for value in semantic_values):
            raise ValueError("workstream must remain at business domain or service granularity")
        for values in (
            self.responsibilities,
            self.source_domains,
            self.required_capabilities,
            self.dependencies,
        ):
            normalized = tuple(value.casefold() for value in values)
            if len(normalized) != len(set(normalized)):
                raise ValueError("workstream lists must contain unique values")
        if self.id in self.dependencies:
            raise ValueError("workstream cannot depend on itself")
        return self


class DomainDecomposition(_ImmutableDomainModel):
    """Validated acyclic set of temporary business workstreams."""

    rationale: Text8192
    workstreams: Annotated[tuple[DomainWorkstream, ...], Field(min_length=1, max_length=32)]

    @field_validator("workstreams", mode="before")
    @classmethod
    def copy_workstreams(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def require_valid_dependency_graph(self) -> Self:
        identifiers = tuple(workstream.id for workstream in self.workstreams)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("workstream IDs must be unique")
        names = tuple(workstream.name.casefold() for workstream in self.workstreams)
        if len(names) != len(set(names)):
            raise ValueError("workstream names must be unique")
        known = set(identifiers)
        dependencies = {
            workstream.id: set(workstream.dependencies) for workstream in self.workstreams
        }
        if any(not values <= known for values in dependencies.values()):
            raise ValueError("workstream dependency must reference an existing workstream")
        domain_counts: dict[str, int] = {}
        for workstream in self.workstreams:
            for source_domain in workstream.source_domains:
                normalized_domain = source_domain.casefold()
                domain_counts[normalized_domain] = domain_counts.get(normalized_domain, 0) + 1
        if any(count > _MAX_WORKSTREAMS_PER_DOMAIN for count in domain_counts.values()):
            raise ValueError("architecture domain is fragmented into too many workstreams")
        resolved: set[str] = set()
        remaining = set(identifiers)
        while remaining:
            ready = {identifier for identifier in remaining if dependencies[identifier] <= resolved}
            if not ready:
                raise ValueError("workstream dependency graph must be acyclic")
            resolved.update(ready)
            remaining.difference_update(ready)
        return self
