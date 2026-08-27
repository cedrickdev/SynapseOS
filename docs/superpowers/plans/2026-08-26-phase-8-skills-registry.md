# Phase 8 Skills Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bounded, immutable local Skills Registry with secure loading, deterministic selection, five original V1 skills, and no Phase 9 behavior.

**Architecture:** Strict core value objects, registry, and selector remain independent of filesystem and YAML. A single infrastructure loader validates one finite local snapshot without links, partial results, retries, caches, or execution. Agent declarations remain inert and Phase 7 remains the sole permission authority.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML SafeLoader, pathlib/os, pytest, Ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-08-26-phase-8-skills-registry-design.md`

## Global Constraints

- Implement Phase 8 only; no workspace manager, write/shell/test runner, loops, MCP, Capability Router, remote installation, hot reload, prompt assembly, or agent-runtime execution.
- Use English for code, comments, examples, skill content, documentation, and commits.
- Follow RED/GREEN/REFACTOR and run focused tests after every behavior change.
- Keep `AgentProfile.skill_ids` declarative and `AgentPermission` as the sole execution authority.
- Never follow symlinks, expose absolute paths or parser errors, return partial registries, retry, cache, access the network, execute content, or own external resources.
- Enforce 1,000 scanned entries, 256 skills, 64 KiB metadata, 256 KiB instructions, 64 collection values, 1,024-character strings, and 128-character identifiers.
- Preserve `CLAUDE.local.md` as untracked local state and never add AI co-author trailers.

---

### Task 1: Strict skill contracts and safe errors

**Files:**
- Replace: `core/skills/__init__.py`
- Create: `core/skills/types.py`
- Create: `core/skills/errors.py`
- Create: `tests/skills/__init__.py`
- Create: `tests/skills/test_types.py`

**Interfaces:**
- Consumes: `core.enums.Permission` and existing canonical identifier conventions.
- Produces: `SkillMetadata`, `Skill`, `SkillSelectionRequest`, `SkillSelectionReason`, `SkillMatch`, and stable skill errors/codes.

- [ ] **Step 1: Write failing immutable metadata and content tests**

```python
def test_skill_metadata_requires_canonical_permissions_and_semver() -> None:
    metadata = SkillMetadata.model_validate(valid_metadata(), strict=True)
    assert metadata.required_permissions == frozenset({Permission.FILESYSTEM_READ})
    assert metadata.version == "1.0.0"


def test_skill_is_immutable_and_instructions_are_bounded() -> None:
    skill = Skill(metadata=metadata(), instructions="# Workflow\nRead before acting.")
    with pytest.raises(ValidationError):
        skill.instructions = "changed"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/skills/test_types.py -q`
Expected: collection fails because Phase 8 contracts do not exist.

- [ ] **Step 3: Implement minimal strict frozen models and sanitized errors**

Use `ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)`. Validate
`MAJOR.MINOR.PATCH`, exact `Permission` instances, copied frozen sets, bounded description/content,
positive `max_results <= 64`, sorted immutable match reasons, and consistent positive scores.

- [ ] **Step 4: Add invalid-ID, unknown-field, raw-string permission, collection, content, and leakage tests**

Assert constant `SkillErrorCode` values and that validation/error representations contain no
secret markers supplied as rejected data.

- [ ] **Step 5: Run focused quality checks**

Run: `.venv/bin/pytest tests/skills/test_types.py -q`
Run: `.venv/bin/ruff check core/skills tests/skills`
Run: `.venv/bin/mypy core/skills tests/skills`

- [ ] **Step 6: Commit**

```bash
git add core/skills tests/skills
git commit -m "feat(skills): add strict skill contracts"
```

---

### Task 2: Immutable registry

**Files:**
- Create: `core/skills/registry.py`
- Modify: `core/skills/__init__.py`
- Create: `tests/skills/test_registry.py`

**Interfaces:**
- Consumes: finite `Iterable[Skill]`.
- Produces: `SkillRegistry(skills)`, `.get(skill_id)`, `.skills`, `.definitions`, and `.ids`.

- [ ] **Step 1: Write failing lookup and deterministic-order tests**

```python
def test_registry_returns_skills_in_stable_id_order() -> None:
    registry = SkillRegistry([skill("testing"), skill("generic-backend")])
    assert registry.ids == ("generic-backend", "testing")
    assert registry.get("testing") == skill("testing")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/skills/test_registry.py -q`
Expected: import failure because `SkillRegistry` is absent.

- [ ] **Step 3: Implement a copied immutable map with no mutation API**

Validate exact `Skill` instances, reject duplicate IDs and more than 256 entries, expose immutable
tuples, and return `None` for a canonical missing ID without fuzzy matching.

- [ ] **Step 4: Add duplicate, forged subtype, source-mutation, and bound tests**

Prove changing the source list after construction does not alter the registry and no register,
replace, or remove method exists.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest tests/skills/test_registry.py tests/skills/test_types.py -q`
Commit: `feat(skills): add immutable skill registry`

---

### Task 3: Secure bounded filesystem loader

**Files:**
- Modify: `pyproject.toml`
- Create: `infrastructure/skills/__init__.py`
- Create: `infrastructure/skills/loader.py`
- Create: `tests/skills/test_loader.py`

**Interfaces:**
- Consumes: existing local `Path` chosen by the caller.
- Produces: `SkillLoader.load(root: Path) -> tuple[Skill, ...]`.

- [ ] **Step 1: Add PyYAML as a direct dependency and write one valid-load test**

```python
def test_loader_reads_one_exact_skill_directory(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", metadata=valid_metadata("testing"))
    assert SkillLoader().load(tmp_path)[0].metadata.id == "testing"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv/bin/pytest tests/skills/test_loader.py::test_loader_reads_one_exact_skill_directory -q`
Expected: import failure because the infrastructure loader is absent.

- [ ] **Step 3: Implement one no-follow, all-or-nothing load path**

Use `os.scandir`, `lstat`, explicit regular-file checks, byte-limited binary reads, strict UTF-8,
a SafeLoader subclass that rejects aliases and custom tags, and strict metadata reconstruction.
Require the exact two filenames and directory/metadata ID equality. Sort candidates by ID only
after validating the complete snapshot.

- [ ] **Step 4: Add the complete adversarial matrix**

Cover missing/extra files, missing root, root/file/directory symlinks, FIFO/non-regular files,
invalid UTF-8, malformed YAML, aliases, custom tags, scalar/list roots, unknown fields, duplicate
metadata IDs, ID mismatch, 1,001 entries, 257 skills, oversized files, and secret/path sanitization.

- [ ] **Step 5: Prove no partial result and no side effects**

Place one valid and one invalid skill together; assert a single `SkillLoadError`, no returned
snapshot, no created files, no network/subprocess calls, and every opened file is closed.

- [ ] **Step 6: Run focused quality checks and commit**

Run: `.venv/bin/pytest tests/skills/test_loader.py -q`
Run: `.venv/bin/ruff check infrastructure/skills tests/skills/test_loader.py pyproject.toml`
Run: `.venv/bin/mypy infrastructure/skills tests/skills/test_loader.py`
Commit: `feat(skills): load bounded local skill snapshots`

---

### Task 4: Deterministic skill selector

**Files:**
- Create: `core/skills/selector.py`
- Modify: `core/skills/__init__.py`
- Create: `tests/skills/test_selector.py`

**Interfaces:**
- Consumes: `SkillRegistry` and strict `SkillSelectionRequest`.
- Produces: `SkillSelector.select(request) -> tuple[SkillMatch, ...]`.

- [ ] **Step 1: Write failing permission-filter and weighted-ranking tests**

```python
def test_selector_filters_permissions_then_applies_stable_weights() -> None:
    matches = SkillSelector(registry()).select(request())
    assert [(match.skill_id, match.score) for match in matches] == [
        ("generic-backend", 18),
        ("testing", 8),
    ]
```

- [ ] **Step 2: Run the selector test and verify RED**

Run: `.venv/bin/pytest tests/skills/test_selector.py -q`
Expected: import failure because `SkillSelector` is absent.

- [ ] **Step 3: Implement exact-token deterministic scoring**

Normalize bounded task and role text to lowercase ASCII identifier tokens, use the exact weights
8/6/4/3/2, emit stable reason codes, exclude missing-permission and zero-score skills, cap results,
and sort by `(-score, skill_id)`.

- [ ] **Step 4: Add individual weight, tie, bound, casing, punctuation, partial-permission, and repeatability tests**

Call selection repeatedly and assert byte-equivalent model dumps. Patch network, subprocess, and
LLM boundaries to fail if touched; selection must remain pure and must not mutate registry/request.

- [ ] **Step 5: Run focused and neighboring checks and commit**

Run: `.venv/bin/pytest tests/skills -q`
Run: `.venv/bin/ruff check core/skills tests/skills`
Run: `.venv/bin/mypy core/skills tests/skills`
Commit: `feat(skills): rank skills deterministically`

---

### Task 5: Five V1 skill packages

**Files:**
- Create: `skills/generic-backend/{SKILL.md,metadata.yaml}`
- Create: `skills/generic-frontend/{SKILL.md,metadata.yaml}`
- Create: `skills/testing/{SKILL.md,metadata.yaml}`
- Create: `skills/git-workflow/{SKILL.md,metadata.yaml}`
- Create: `skills/security-review/{SKILL.md,metadata.yaml}`
- Create: `tests/skills/test_builtin_skills.py`

**Interfaces:**
- Consumes: secure loader and Phase 6/7 canonical tool/permission IDs.
- Produces: five validated original V1 skills.

- [ ] **Step 1: Write a failing exact built-in snapshot test**

```python
def test_builtin_skill_snapshot_is_exact_and_valid() -> None:
    skills = SkillLoader().load(Path("skills"))
    assert tuple(skill.metadata.id for skill in skills) == (
        "generic-backend",
        "generic-frontend",
        "git-workflow",
        "security-review",
        "testing",
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv/bin/pytest tests/skills/test_builtin_skills.py -q`
Expected: loader rejects the absent root or returns no skills.

- [ ] **Step 3: Add concise original English metadata and instructions**

Use version `1.0.0`, only `read_file`, `list_files`, `search_text`, `git_status`, and `git_diff`
recommendations, and only canonical Phase 7 permissions. Include purpose, workflow, stop/escalation
conditions, deterministic verification, security, and prohibited actions without scripts or hidden
prompt directives.

- [ ] **Step 4: Add constitutional and cross-reference tests**

Assert every recommended tool exists in the default registry, every permission is canonical,
content contains no secret-looking values or external URLs, and each skill states bounded evidence,
failure visibility, and escalation expectations relevant to its craft.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest tests/skills/test_builtin_skills.py tests/tools/test_default_registry.py -q`
Commit: `feat(skills): add five built-in skill packages`

---

### Task 6: Declarative agent compatibility and regression proof

**Files:**
- Modify: `tests/agents/test_types.py`
- Create: `tests/skills/test_agent_compatibility.py`

**Interfaces:**
- Consumes: `AgentProfile.skill_ids` and `SkillRegistry`.
- Produces: evidence that declarations can be resolved explicitly but cannot execute or grant.

- [ ] **Step 1: Write compatibility tests**

Validate known IDs against the loaded registry in test composition, assert unknown declarations are
reported by an explicit helper, and prove creating/selecting skills leaves profiles, tool calls,
permission grants, prompts, and histories unchanged.

- [ ] **Step 2: Run and verify any expected RED**

Run: `.venv/bin/pytest tests/skills/test_agent_compatibility.py tests/agents -q`

- [ ] **Step 3: Add only the minimal pure registry helper if required**

Add `SkillRegistry.missing_ids(ids: Iterable[str]) -> tuple[str, ...]`; do not modify Agent runtime,
LLM requests, ToolExecutor, PermissionEngine, or persistence.

- [ ] **Step 4: Run Phase 5-8 regressions and commit**

Run: `.venv/bin/pytest tests/agents tests/skills tests/tools tests/permissions -q`
Commit: `test(skills): verify inert agent skill declarations`

---

### Task 7: Documentation, checklist, and complete acceptance

**Files:**
- Create: `docs/skills.md`
- Create: `docs/adr/0008-local-versioned-skills-registry.md`
- Modify: `docs/adr/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Documents: format, limits, loading, deterministic selection, permission distinction, composition, and explicit Phase 9 boundary.

- [ ] **Step 1: Document contracts and ADR**

Document a safe explicit load/registry/select example, score table, all limits, error sanitization,
and why local versioned files beat premature PostgreSQL/remote registries in V1.

- [ ] **Step 2: Update only verified Phase 8 repository status and boxes**

Mark the nine metadata items, five V1 skills, and Phase 8 implementation complete only after their
tests pass. Leave Phase 9 and later unchanged.

- [ ] **Step 3: Run fresh complete verification**

Run: `.venv/bin/pytest` — all tests, including real PostgreSQL, pass without warnings.
Run: `.venv/bin/ruff check .` — no findings.
Run: `.venv/bin/ruff format --check .` — every file formatted.
Run: `.venv/bin/mypy .` — strict typing passes.
Run: `docker compose exec -T api alembic current` — `20260826_0003 (head)`.
Run: `docker compose exec -T api alembic check` — no upgrade operations.

- [ ] **Step 4: Verify Docker and health**

Run: `docker compose up -d --build`, `docker compose ps`, and
`curl --fail --silent http://localhost:8000/health`; require healthy API/PostgreSQL and
`{"status":"ok"}`.

- [ ] **Step 5: Audit scope, secrets, contributors, and diff**

Run `git diff --check`, inspect `git diff --name-only phase-7/permission-engine...HEAD`, scan tracked
changes for high-confidence credentials and co-author trailers, confirm `CLAUDE.local.md` is not
tracked, and confirm no Phase 9 implementation or generated report.

- [ ] **Step 6: Commit, push, and open the stacked PR**

Commit: `docs(skills): document verified Phase 8 registry`. Push `phase-8/skills-registry` and open
a PR against `phase-7/permission-engine`. Do not merge or start Phase 9.
