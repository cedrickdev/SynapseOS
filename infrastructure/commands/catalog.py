"""Immutable built-in command profile catalog."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from core.commands import CommandCategory, CommandProfileId


@dataclass(frozen=True, slots=True)
class CommandTemplate:
    """Application-owned process vector before executable/workspace resolution."""

    profile_id: CommandProfileId
    category: CommandCategory
    executable_name: str | None
    arguments: tuple[str, ...]


_TEMPLATES = (
    CommandTemplate(CommandProfileId.PYTEST, CommandCategory.TEST, None, ("-m", "pytest")),
    CommandTemplate(
        CommandProfileId.RUFF,
        CommandCategory.LINT,
        None,
        ("-m", "ruff", "check", "."),
    ),
    CommandTemplate(CommandProfileId.MYPY, CommandCategory.LINT, None, ("-m", "mypy", ".")),
    CommandTemplate(
        CommandProfileId.NPM_TEST,
        CommandCategory.TEST,
        "npm",
        ("test", "--ignore-scripts=false"),
    ),
    CommandTemplate(CommandProfileId.NPM_BUILD, CommandCategory.BUILD, "npm", ("run", "build")),
    CommandTemplate(
        CommandProfileId.PHP_ARTISAN_TEST,
        CommandCategory.TEST,
        "php",
        ("artisan", "test"),
    ),
    CommandTemplate(
        CommandProfileId.GIT_STATUS,
        CommandCategory.GIT_READ,
        "git",
        ("status", "--short", "--branch", "--untracked-files=all"),
    ),
    CommandTemplate(
        CommandProfileId.GIT_DIFF,
        CommandCategory.GIT_READ,
        "git",
        ("diff", "--no-ext-diff", "--no-textconv", "--no-color"),
    ),
    CommandTemplate(
        CommandProfileId.GIT_DIFF_STAGED,
        CommandCategory.GIT_READ,
        "git",
        ("diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-color"),
    ),
    CommandTemplate(
        CommandProfileId.GIT_LOG,
        CommandCategory.GIT_READ,
        "git",
        ("log", "-n", "50", "--format=%H%x09%aI%x09%s", "--no-decorate"),
    ),
)


class BuiltinCommandCatalog:
    """Read-only catalog of the complete Phase 11 command surface."""

    def __init__(self) -> None:
        self._templates = MappingProxyType({item.profile_id: item for item in _TEMPLATES})
        if len(self._templates) != len(_TEMPLATES):
            raise RuntimeError("Built-in command catalog is invalid.")

    @property
    def profile_ids(self) -> tuple[CommandProfileId, ...]:
        return tuple(self._templates)

    def template(self, profile_id: CommandProfileId) -> CommandTemplate:
        return self._templates[profile_id]
