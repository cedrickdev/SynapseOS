# Phase 8 Skills Registry Design

- **Status:** Approved design
- **Date:** 2026-08-26
- **Scope:** Phase 8 only

## Objective

Provide a deterministic, provider-neutral registry of versioned instructional capabilities that
agents can load explicitly for a mission. A skill is data: validated metadata plus bounded Markdown
instructions. Loading a skill never executes code, invokes a model, calls a tool, or grants a
permission.

## Source and directory contract

The V1 source is one caller-selected local root with this exact layout:

```text
skills/
└── <skill-id>/
    ├── SKILL.md
    └── metadata.yaml
```

Only direct child directories are discovered. Each accepted directory contains exactly the two
required regular UTF-8 files. The loader rejects symlinks for the root, skill directory, and both
files; path traversal; non-regular files; duplicate IDs; metadata/directory ID mismatch; invalid
YAML; unknown metadata fields; and malformed content. It never scans recursively beyond a skill
directory and never follows links.

Resource limits are fixed constants:

- at most 1,000 discovered directory entries;
- at most 256 skills;
- `metadata.yaml` at most 64 KiB;
- `SKILL.md` at most 256 KiB;
- at most 64 values in any metadata collection;
- metadata strings at most 1,024 characters and identifiers at most 128 characters.

Files are read once per explicit load. V1 has no watcher, cache, background refresh, remote source,
fallback, or retry.

## Core contracts

### `SkillMetadata`

An immutable strict value object containing:

- `id`: lowercase canonical identifier matching its directory;
- `name`: bounded display name;
- `description`: bounded selection summary;
- `domains`: immutable canonical identifier set;
- `technologies`: immutable canonical identifier set;
- `tags`: immutable canonical identifier set;
- `version`: strict `MAJOR.MINOR.PATCH` semantic version without ranges;
- `recommended_tool_ids`: immutable canonical tool-ID set;
- `required_permissions`: immutable set of the Phase 7 `Permission` enum.

Collections are non-empty where meaningful and are copied into frozen sets. Unknown permission
identifiers fail validation. Metadata cannot add execution authority; required permissions are
selection prerequisites only.

### `Skill`

An immutable value object containing validated `SkillMetadata` and bounded non-empty Markdown
instructions. It stores no source path, file handle, mutable YAML object, executable callback, or
provider-specific state.

### `SkillLoader`

`SkillLoader.load(root: Path) -> tuple[Skill, ...]` validates the full local snapshot before
returning it. Any invalid candidate fails the whole load with a stable sanitized `SkillLoadError`;
partial registries are never returned. Errors never expose file contents, absolute host paths,
parser details, or exception text.

YAML uses `safe_load` and must decode to one mapping. YAML aliases/custom constructors and other
features that could produce unsafe or surprising object graphs are rejected by strict shape and
size validation. `PyYAML` becomes a direct runtime dependency rather than relying on a transitive
dependency.

### `SkillRegistry`

The registry receives an already validated finite iterable and creates an immutable ID map. It
exposes only deterministic `get`, `list`, and definitions. It has no runtime registration,
replacement, removal, filesystem access, or global singleton. Duplicate IDs fail construction.

### `SkillSelector`

The selector receives a strict bounded `SkillSelectionRequest` with:

- task description;
- agent role;
- task domains;
- technologies;
- tags;
- available canonical permissions;
- maximum result count.

Skills whose required permissions are not a subset of available permissions are excluded. This is
not an authorization decision: Phase 7 still evaluates current PostgreSQL grants before every tool
execution.

Remaining skills receive an integer score:

- +8 for each requested domain match;
- +6 for each requested technology match;
- +4 for each requested tag match;
- +3 when a normalized metadata token appears in the bounded task description;
- +2 when a normalized metadata token appears in the agent role.

Only positive scores are returned. Results contain the skill ID, score, and sorted stable reason
codes, never the full instructions. Ties sort by descending score then ascending skill ID. The
algorithm is case-insensitive, exact-token based, bounded, deterministic, and performs no LLM,
network, fuzzy, embedding, or regex work.

## Five V1 skills

The repository includes original, concise English content for:

- `generic-backend`;
- `generic-frontend`;
- `testing`;
- `git-workflow`;
- `security-review`.

Their metadata references only existing Phase 6 tool IDs and Phase 7 permission IDs. Instructions
must preserve the Company Constitution: deterministic evidence outranks confidence, failures are
never hidden, least privilege applies, secrets are excluded, author and reviewer differ, and
irreversible actions require approval.

## Agent integration boundary

`AgentProfile.skill_ids` remains an immutable declaration. Phase 8 may validate that requested IDs
exist and allow explicit retrieval, but it does not modify the agent runtime, automatically inject
instructions into LLM prompts, execute skill instructions, select tools, or grant permissions.
Runtime prompt assembly belongs to a later explicitly scoped integration phase.

## Error handling and security

Public errors use stable codes for invalid input, unsafe path, invalid metadata, invalid content,
duplicate ID, resource limit, and unknown skill. Messages are constant and sanitized. No raw YAML,
Markdown, path, parser exception, environment value, or secret is logged or persisted.

The subsystem performs no persistence, subprocess, network access, retries, dynamic imports,
template evaluation, shell expansion, or resource ownership beyond bounded local file reads.

## Testing

Strict TDD covers:

- immutable model validation and exact permission typing;
- valid loading of the five repository skills;
- malformed YAML, unknown fields, custom tags, duplicate IDs, ID mismatch, invalid UTF-8;
- path traversal, symlinks, non-regular files, missing/extra files, and all resource limits;
- all-or-nothing load behavior and sanitized errors;
- immutable deterministic registry behavior;
- selector weights, stable ties, result bounds, role/task/domain/tag/technology matching;
- exclusion for missing or partial permissions;
- proof that selection does not execute tools, invoke LLMs, access the network, or grant authority;
- regressions for existing agents, tools, permissions, PostgreSQL migrations, and API health.

Filesystem tests use temporary directories. Persistence regressions continue to use real
PostgreSQL migrated by Alembic; Phase 8 adds no migration.

## Documentation and completion

Add a skills guide and ADR, update README and AGENTS, and check only verified Phase 8 boxes. Final
acceptance requires the complete pytest suite, Ruff check and format check, strict mypy, Alembic
current/check, Docker health, secret/contributor scan, and a dedicated stacked PR based on
`phase-7/permission-engine`.

## Explicit exclusions

Phase 8 does not implement workspace management, write tools, command/test runners, loop
engineering, skill marketplace or remote installation, signatures/trust distribution, database
skill persistence, hot reload, LLM selection, embeddings, Capability Router, MCP, prompt assembly,
automatic agent loading, approval workflow, or any Phase 9+ feature.
