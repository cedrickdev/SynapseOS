"""Secure bounded loader for one local versioned skill snapshot."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.events import AliasEvent

from core.enums import Permission
from core.skills import Skill, SkillErrorCode, SkillLoadError, SkillMetadata

_METADATA_FILE = "metadata.yaml"
_INSTRUCTIONS_FILE = "SKILL.md"
_EXPECTED_FILES = frozenset({_METADATA_FILE, _INSTRUCTIONS_FILE})
_MAX_DIRECTORY_ENTRIES = 1_000
_MAX_SKILLS = 256
_MAX_METADATA_BYTES = 64 * 1_024
_MAX_INSTRUCTION_BYTES = 256 * 1_024


class _NoAliasSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that also rejects aliases before object construction."""

    def compose_node(self, parent: Any, index: Any) -> yaml.Node:
        if self.check_event(AliasEvent):
            raise yaml.YAMLError("aliases are not supported")
        node = super().compose_node(parent, index)
        if node is None:
            raise yaml.YAMLError("empty node")
        return node


class SkillLoader:
    """Load an all-or-nothing local snapshot without following links."""

    def load(self, root: Path) -> tuple[Skill, ...]:
        """Return a validated stable snapshot or one sanitized failure."""
        self._validate_root(root)
        try:
            with os.scandir(root) as iterator:
                entries = list(iterator)
        except OSError as error:
            error.__traceback__ = None
            del error
            raise self._unsafe_path() from None
        if len(entries) > _MAX_DIRECTORY_ENTRIES:
            raise self._resource_limit()
        if any(entry.is_symlink() or not entry.is_dir(follow_symlinks=False) for entry in entries):
            raise self._unsafe_path()

        skills: list[Skill] = []
        seen_ids: set[str] = set()
        for entry in entries:
            if len(skills) >= _MAX_SKILLS:
                raise self._resource_limit()
            skill = self._load_directory(Path(entry.path), entry.name)
            if skill.metadata.id in seen_ids:
                raise SkillLoadError(
                    SkillErrorCode.DUPLICATE_ID,
                    "Skill snapshot contains a duplicate identifier.",
                )
            seen_ids.add(skill.metadata.id)
            skills.append(skill)
        return tuple(sorted(skills, key=lambda skill: skill.metadata.id))

    @staticmethod
    def _validate_root(root: Path) -> None:
        try:
            if (
                not isinstance(root, Path)
                or stat.S_ISLNK(root.lstat().st_mode)
                or not root.is_dir()
            ):
                raise ValueError
        except (OSError, ValueError):
            raise SkillLoader._unsafe_path() from None

    def _load_directory(self, directory: Path, directory_id: str) -> Skill:
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError as error:
            error.__traceback__ = None
            del error
            raise self._unsafe_path() from None
        if any(entry.is_symlink() or not entry.is_file(follow_symlinks=False) for entry in entries):
            raise self._unsafe_path()
        if {entry.name for entry in entries} != _EXPECTED_FILES:
            raise SkillLoadError(
                SkillErrorCode.INVALID_CONTENT,
                "Skill directory content is invalid.",
            )

        metadata_bytes = self._read_regular_file(directory / _METADATA_FILE, _MAX_METADATA_BYTES)
        instruction_bytes = self._read_regular_file(
            directory / _INSTRUCTIONS_FILE,
            _MAX_INSTRUCTION_BYTES,
        )
        metadata = self._parse_metadata(metadata_bytes)
        if metadata.id != directory_id:
            raise SkillLoadError(
                SkillErrorCode.INVALID_METADATA,
                "Skill metadata is invalid.",
            )
        try:
            instructions = instruction_bytes.decode("utf-8")
            return Skill(metadata=metadata, instructions=instructions)
        except (UnicodeDecodeError, ValidationError, ValueError) as error:
            error.__traceback__ = None
            del error
            raise SkillLoadError(
                SkillErrorCode.INVALID_CONTENT,
                "Skill instructions are invalid.",
            ) from None

    @staticmethod
    def _read_regular_file(path: Path, maximum_bytes: int) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(path, flags)
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > maximum_bytes:
                raise ValueError
            data = os.read(descriptor, maximum_bytes + 1)
            if len(data) > maximum_bytes:
                raise ValueError
            return data
        except ValueError:
            raise SkillLoader._resource_limit() from None
        except OSError as error:
            error.__traceback__ = None
            del error
            raise SkillLoader._unsafe_path() from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _parse_metadata(content: bytes) -> SkillMetadata:
        try:
            text = content.decode("utf-8")
            raw = yaml.load(text, Loader=_NoAliasSafeLoader)
            if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
                raise ValueError
            values = dict(raw)
            permissions = values.get("required_permissions")
            if not isinstance(permissions, list):
                raise ValueError
            values["required_permissions"] = frozenset(
                Permission(permission) for permission in permissions
            )
            return SkillMetadata.model_validate(values, strict=True)
        except (
            UnicodeDecodeError,
            ValueError,
            TypeError,
            yaml.YAMLError,
            ValidationError,
        ) as error:
            error.__traceback__ = None
            del error
            raise SkillLoadError(
                SkillErrorCode.INVALID_METADATA,
                "Skill metadata is invalid.",
            ) from None

    @staticmethod
    def _unsafe_path() -> SkillLoadError:
        return SkillLoadError(
            SkillErrorCode.UNSAFE_PATH,
            "Skill snapshot path is unsafe.",
        )

    @staticmethod
    def _resource_limit() -> SkillLoadError:
        return SkillLoadError(
            SkillErrorCode.RESOURCE_LIMIT,
            "Skill snapshot exceeds a resource limit.",
        )
