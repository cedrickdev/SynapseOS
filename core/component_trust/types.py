"""Strict input contracts for component trust manifests."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ComponentType(StrEnum):
    """Executable component categories admitted by the trust registry."""

    AGENT_PACKAGE = "AGENT_PACKAGE"
    SKILL = "SKILL"
    MCP_SERVER = "MCP_SERVER"
    PLAYBOOK = "PLAYBOOK"
    TOOL_PLUGIN = "TOOL_PLUGIN"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class ComponentTrustLevel(StrEnum):
    """Security classification produced by an explicit component scan."""

    APPROVED = "APPROVED"
    RESTRICTED = "RESTRICTED"
    QUARANTINED = "QUARANTINED"


class ComponentTrustManifestInput(BaseModel):
    """Bounded supply-chain evidence accepted by the persistent registry."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    component_id: UUID
    component_type: ComponentType
    name: Annotated[str, Field(min_length=1, max_length=255)]
    version: Annotated[str, Field(min_length=1, max_length=128)]
    source_repository: Annotated[str, Field(min_length=1, max_length=2_048)]
    publisher: Annotated[str, Field(min_length=1, max_length=255)]
    signature: Annotated[str, Field(min_length=1, max_length=2_048)]
    checksum: Annotated[str, Field(min_length=1, max_length=255)]
    requested_capabilities: Annotated[tuple[str, ...], Field(max_length=128)]
    network_access: Annotated[tuple[str, ...], Field(max_length=128)]
    filesystem_access: Annotated[tuple[str, ...], Field(max_length=128)]
    data_access: Annotated[tuple[str, ...], Field(max_length=128)]
    security_findings: Annotated[tuple[str, ...], Field(max_length=256)]
    last_scan_at: datetime
    trust_level: ComponentTrustLevel
    scan_policy_version: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator(
        "name",
        "version",
        "source_repository",
        "publisher",
        "signature",
        "checksum",
        "scan_policy_version",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("component trust text must be trimmed and content-safe")
        return value

    @field_validator(
        "requested_capabilities",
        "network_access",
        "filesystem_access",
        "data_access",
        "security_findings",
    )
    @classmethod
    def validate_entries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("component trust entries must be unique")
        if any(
            not item
            or len(item) > 512
            or item != item.strip()
            or any(ord(character) < 32 for character in item)
            for item in value
        ):
            raise ValueError("component trust entries must be bounded and content-safe")
        return value

    @field_validator("last_scan_at")
    @classmethod
    def validate_last_scan_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("last_scan_at must be UTC-aware")
        return value
