# Skills Registry

Phase 8 provides a bounded local registry of versioned instructional capabilities. A skill is
validated metadata plus Markdown instructions. It is data only: loading or selecting a skill never
executes code, invokes an LLM, calls a tool, persists content, accesses the network, or grants a
permission.

## Package format

```text
skills/
└── <skill-id>/
    ├── SKILL.md
    └── metadata.yaml
```

`metadata.yaml` contains `id`, `name`, `description`, `domains`, `technologies`, `tags`, a strict
semantic `version`, `recommended_tool_ids`, and canonical `required_permissions`. Unknown fields
and raw non-canonical permission values are rejected.

The built-in V1 snapshot contains `generic-backend`, `generic-frontend`, `testing`, `git-workflow`,
and `security-review`.

## Loading and registry composition

```python
skills = SkillLoader().load(Path("skills"))
registry = SkillRegistry(skills)
```

The caller explicitly selects the root. The loader accepts only direct skill directories containing
exactly the two regular UTF-8 files. It rejects links, malformed or surprising YAML, aliases,
custom tags, ID mismatches, partial snapshots, and resource-limit violations. Public errors are
stable and contain no source content, absolute path, parser exception, or environment data.

Limits are fixed:

- 1,000 root entries and 256 valid skills;
- 64 KiB per metadata file and 256 KiB per instruction file;
- YAML nesting depth of at most 32 nodes, with aliases disabled;
- 64 values per metadata collection;
- 1,024 characters per bounded metadata text and 128 per identifier.

There is no cache, watcher, retry, fallback, recursive discovery, remote source, or global registry.
The registry copies the finite snapshot and exposes deterministic lookup/listing only.

## Deterministic selection

`SkillSelector` first excludes skills whose required permissions are unavailable in the supplied
selection context. This is eligibility only: Phase 7 still resolves current PostgreSQL grants before
every tool execution.

Eligible skills receive fixed integer weights:

| Match | Weight |
|---|---:|
| Each domain | 8 |
| Each technology | 6 |
| Each tag | 4 |
| Any exact metadata token in task description | 3 |
| Any exact metadata token in agent role | 2 |

Only positive results are returned. Each result has an ID, score, and stable reasons. Ties use
ascending skill ID after descending score. Matching is case-insensitive and exact-token based; it
uses no model, embedding, fuzzy search, regex supplied by users, network, persistence, or mutation.

## Agent boundary

`AgentProfile.skill_ids` remains an inert immutable declaration. `SkillRegistry.missing_ids()` can
validate a declaration against one explicit snapshot. Phase 8 does not inject instructions into
prompts, modify the runtime agent, select tools, execute workflows, or grant capabilities.

## Deliberate exclusions

Phase 8 adds no workspace manager, write/shell/test tools, loops, skill marketplace, remote install,
signature distribution, database persistence, hot reload, Capability Router, MCP, prompt assembly,
or automatic loading. These require separately approved later phases.
