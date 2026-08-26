# Phase 7 Permission Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace caller-supplied tool permission membership with a database-backed, deny-by-default, explainable, and audited Permission Engine.

**Architecture:** Core permission value objects, policy/audit ports, and a central engine remain independent of SQLAlchemy. Infrastructure verifies the complete agent/run/task/project scope, resolves active PostgreSQL grants, and appends sanitized permission audit events; `ToolExecutor` executes only an `ALLOW` decision.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, PostgreSQL 16, Alembic, asyncio, pytest, Ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-08-26-phase-7-permission-engine-design.md`

## Global Constraints

- Implement Phase 7 only; do not add Phase 8 skills, write/shell/network/database/deployment tools, approval workflows, role inheritance, MCP, RLS, triggers, or permission administration APIs.
- Keep code, comments, docstrings, migrations, tests, and new documentation in English.
- Follow strict TDD: write one behavior test, observe the expected failure, implement the minimum, and rerun focused plus neighboring tests.
- Use real PostgreSQL migrated through Alembic for every persistence test; never use SQLite or `metadata.create_all()`.
- Treat PostgreSQL `AgentPermission` rows as the only execution authority; profile/context permission sets cannot grant authority.
- Use exactly the eleven V1 permission values from the approved specification.
- Resolve permission scope with agent slug, agent run, task, and project in one coherent query.
- Execute a tool only for `ALLOW`; both `DENY` and `ASK` are non-executing terminal outcomes.
- Audit every completed policy decision before tool execution and fail closed if policy or permission auditing fails.
- Persist no tool arguments, paths, source content, prompts, raw results, environment values, credentials, exception text, absolute host paths, unrelated grants, grantor identity, or expiry values in permission audit data.
- Perform no retries, fallback, network calls, caches, implicit grants, wildcard matching, background work, commit, rollback, or resource close.
- Preserve `CLAUDE.local.md` as untracked local state; never stage it.

---

### Task 1: Canonical permission types and safe errors

**Files:**
- Modify: `core/enums.py`
- Replace: `core/permissions/__init__.py`
- Create: `core/permissions/types.py`
- Create: `core/permissions/errors.py`
- Create: `tests/permissions/__init__.py`
- Create: `tests/permissions/test_types.py`

**Interfaces:**
- Produces: `Permission`, `PermissionOutcome`, `PermissionReasonCode`, `PermissionRequest`, `PolicyRequest`, `PermissionDecision`, and `ToolPermission`.
- Produces: sanitized `PermissionError`, `PermissionInputError`, `PermissionPolicyError`, and `PermissionAuditError`.

- [ ] **Step 1: Write the failing canonical-enum test**

```python
def test_permission_enum_contains_exactly_v1_values() -> None:
    assert tuple(permission.value for permission in Permission) == (
        "filesystem.read", "filesystem.write", "git.read", "git.write",
        "shell.execute", "tests.execute", "network.access", "database.read",
        "database.write", "deployment.staging", "deployment.production",
    )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/permissions/test_types.py::test_permission_enum_contains_exactly_v1_values -q`  
Expected: collection fails because `Permission` and Phase 7 types do not exist.

- [ ] **Step 3: Add the shared enum and strict immutable models**

Implement uppercase enum names with the exact lowercase values. Use `ConfigDict(frozen=True,
extra="forbid", hide_input_in_errors=True)`, existing identifier syntax, bounded immutable sets,
UUID scope fields, timezone-aware UTC timestamps, and constant-safe messages.

```python
class PermissionOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ASK = "ASK"


class PermissionRequest(_ImmutablePermissionModel):
    agent_id: Identifier
    agent_run_id: UUID
    project_id: UUID
    task_id: UUID
    tool_name: Identifier
    risk_level: ToolRiskLevel
    required_permission_ids: IdentifierSet
    correlation_id: UUID
```

- [ ] **Step 4: Add strictness, immutability, unknown, and leak-resistance tests**

Cover mutable inputs copied to frozensets, blank/oversized identifiers, extras, malformed UUIDs,
naive timestamps, model mutation, unknown permission IDs retained only at the outer request, and
validation messages that do not echo rejected marker values.

- [ ] **Step 5: Implement canonical policy values and error hierarchy**

`PolicyRequest` contains `frozenset[Permission]`; `ToolPermission` maps one tool to canonical
permissions; `PermissionDecision` requires consistent outcome/reason combinations and contains only
scope, sorted required permission values, one reason, safe message, correlation ID, and UTC time.

- [ ] **Step 6: Run focused quality checks**

Run: `.venv/bin/pytest tests/permissions/test_types.py -q`  
Run: `.venv/bin/ruff check core/enums.py core/permissions tests/permissions`  
Run: `.venv/bin/mypy core/enums.py core/permissions tests/permissions`

- [ ] **Step 7: Commit**

```bash
git add core/enums.py core/permissions tests/permissions
git commit -m "feat(permissions): add strict permission contracts"
```

---

### Task 2: AgentPermission model and reversible Alembic migration

**Files:**
- Modify: `infrastructure/database/models/organization.py`
- Modify: `infrastructure/database/models/__init__.py`
- Create: `alembic/versions/20260826_0003_permission_engine.py`
- Create: `tests/database/test_permission_models.py`
- Modify: `tests/database/test_migrations.py`

**Interfaces:**
- Consumes: `core.enums.Permission`, existing `AuditActorType`, ORM base mixins, `Agent`, and `Project`.
- Produces: ORM `AgentPermission` and migration revision `20260826_0003`.

- [ ] **Step 1: Write failing ORM metadata and constraint tests**

```python
def test_agent_permission_has_required_columns_and_indexes() -> None:
    table = AgentPermission.__table__
    assert set(table.columns) == {
        "id", "agent_id", "permission", "project_id", "granted_by_actor_type",
        "granted_by_actor_id", "reason", "expires_at", "revoked_at", "created_at",
    }
    assert table.c.permission.type.name == "permission"
```

Add real-PostgreSQL tests proving an `AGENT` grantor, expiry before creation, revocation before
creation, duplicate global grants, and duplicate project grants fail; matching permissions across
different projects remain valid.

- [ ] **Step 2: Run the model test and verify RED**

Run: `.venv/bin/pytest tests/database/test_permission_models.py -q`  
Expected: collection fails because `AgentPermission` does not exist.

- [ ] **Step 3: Implement the minimal ORM model and relationships**

Use UUID/UTC primitives from `database/base.py`, `Enum(Permission, name="permission")`, bounded
strings, timezone-aware timestamps, check constraints, partial unique indexes for global/project
scope, and lookup/expiry indexes. Add `permissions` relationships to `Agent` and `Project` without
delete cascades.

- [ ] **Step 4: Write migration upgrade/downgrade tests before the migration**

Extend the migration suite to upgrade from `20260825_0002` to head, inspect the enum/table/indexes,
downgrade to `20260825_0002`, verify both table and enum are absent, and re-upgrade to head.

- [ ] **Step 5: Run the migration test and verify RED**

Run: `.venv/bin/pytest tests/database/test_migrations.py -q`  
Expected: failure because revision `20260826_0003` and `agent_permissions` are absent.

- [ ] **Step 6: Implement the reversible migration**

Create the enum before the table; create named foreign keys, checks, lookup indexes, and two partial
unique indexes. Downgrade in reverse dependency order and explicitly drop the PostgreSQL enum.

- [ ] **Step 7: Run model, migration, and schema checks**

Run: `.venv/bin/pytest tests/database/test_permission_models.py tests/database/test_migrations.py tests/database/test_constraints.py -q`  
Run: `.venv/bin/ruff check infrastructure/database alembic/versions tests/database`  
Run: `.venv/bin/mypy infrastructure/database alembic/versions tests/database`

- [ ] **Step 8: Commit**

```bash
git add core/enums.py infrastructure/database/models alembic/versions tests/database
git commit -m "feat(database): persist scoped agent permissions"
```

---

### Task 3: Provider-neutral policy and deterministic policy engine

**Files:**
- Create: `core/permissions/policy.py`
- Create: `core/permissions/audit.py`
- Create: `core/permissions/engine.py`
- Modify: `core/permissions/__init__.py`
- Create: `tests/permissions/fakes.py`
- Create: `tests/permissions/test_engine.py`

**Interfaces:**
- Consumes: Task 1 value objects.
- Produces: `PermissionPolicy.evaluate(request, evaluated_at) -> PermissionDecision`, `PermissionAuditRecorder.record(decision)`, and `PermissionEngine.evaluate(request) -> PermissionDecision`.

- [ ] **Step 1: Write a failing allowed-decision lifecycle test**

```python
def test_engine_canonicalizes_evaluates_once_and_audits_allow(valid_request: PermissionRequest) -> None:
    policy = RecordingPolicy(PermissionOutcome.ALLOW, PermissionReasonCode.GRANTED)
    audit = RecordingPermissionAudit()
    decision = PermissionEngine(policy, audit, clock=fixed_clock).evaluate(valid_request)
    assert decision.outcome is PermissionOutcome.ALLOW
    assert policy.calls == 1
    assert audit.decisions == [decision]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/permissions/test_engine.py::test_engine_canonicalizes_evaluates_once_and_audits_allow -q`  
Expected: failure because policy, audit, and engine contracts do not exist.

- [ ] **Step 3: Implement one canonical ALLOW path**

Capture the injected UTC clock once, reconstruct the strict request, convert every ID with
`Permission(identifier)`, build `PolicyRequest`, call the policy exactly once, strictly revalidate
its decision, call audit exactly once, and return it. Injected dependencies are never closed.

- [ ] **Step 4: Add unknown, failure, ownership, and no-retry tests**

Prove unknown permission returns audited `DENY/UNKNOWN_PERMISSION` without policy invocation;
malformed requests fail before policy; policy errors raise sanitized `PermissionPolicyError`;
audit errors raise sanitized `PermissionAuditError`; mismatched or malformed policy decisions fail
closed; and no retry/commit/rollback/close methods are called.

- [ ] **Step 5: Implement deny-by-default and sanitized failures**

Unknown permission decisions contain no rejected identifier. Clear references to raw request
values in failure paths. Do not audit an evaluation that failed before a coherent decision exists;
do require audit success before returning any completed decision.

- [ ] **Step 6: Run focused and neighboring checks**

Run: `.venv/bin/pytest tests/permissions -q`  
Run: `.venv/bin/ruff check core/permissions tests/permissions`  
Run: `.venv/bin/mypy core/permissions tests/permissions`

- [ ] **Step 7: Commit**

```bash
git add core/permissions tests/permissions
git commit -m "feat(permissions): enforce audited policy evaluation"
```

---

### Task 4: SQLAlchemy scope and grant policy

**Files:**
- Create: `infrastructure/permissions/__init__.py`
- Create: `infrastructure/permissions/policy.py`
- Create: `tests/database/permission_fixtures.py`
- Create: `tests/database/test_permission_policy.py`

**Interfaces:**
- Consumes: `PermissionPolicy`, `PolicyRequest`, `PermissionDecision`, `AgentPermission`, `AgentRun`, `Agent`, `Task`, and caller-owned `Session`.
- Produces: `SQLAlchemyPermissionPolicy.evaluate(request, evaluated_at) -> PermissionDecision`.

- [ ] **Step 1: Write failing global and project ALLOW tests**

```python
def test_policy_allows_active_global_grant(db_session: Session, policy_scope: PolicyScope) -> None:
    add_permission(db_session, policy_scope.agent, Permission.FILESYSTEM_READ)
    decision = SQLAlchemyPermissionPolicy(db_session).evaluate(
        policy_scope.request({Permission.FILESYSTEM_READ}), policy_scope.now
    )
    assert decision.outcome is PermissionOutcome.ALLOW
    assert decision.reason_code is PermissionReasonCode.GRANTED
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/database/test_permission_policy.py::test_policy_allows_active_global_grant -q`  
Expected: import failure because the SQLAlchemy policy does not exist.

- [ ] **Step 3: Implement coherent scope verification and active-grant resolution**

Use one joined scope query over `AgentRun`, `Agent`, and `Task` constrained by all supplied IDs and
slug. Load only required permission rows where project scope is global or matches, `revoked_at IS
NULL`, and expiry is absent or after the single evaluation timestamp. Return constant-safe
decisions and never expose grant rows.

- [ ] **Step 4: Add complete policy matrix tests**

Cover no grant, one missing permission from a multi-permission request, expired, revoked,
cross-project, wrong agent slug, wrong run/task/project, missing rows, global/project union,
autonomy levels 0–4, and mandatory `deployment.production` `ASK`. Prove rule precedence exactly
matches the specification.

- [ ] **Step 5: Implement autonomy and approval rules**

Keep the minimum-level mapping immutable and exhaustive for all eleven enum values. Missing grants
must return `DENY` before autonomy is considered. Production returns human `ASK` even at autonomy 4
or 5. No query is retried or cached.

- [ ] **Step 6: Add transaction/resource ownership and sanitization tests**

Patch session `commit`, `rollback`, and `close` to fail if called. Force a SQLAlchemy error and
assert only `PermissionPolicyError` with a constant message escapes; no UUID, slug, SQL, password,
or database URL appears.

- [ ] **Step 7: Run PostgreSQL and quality checks**

Run: `.venv/bin/pytest tests/database/test_permission_policy.py tests/database/test_permission_models.py -q`  
Run: `.venv/bin/ruff check infrastructure/permissions tests/database/permission_fixtures.py tests/database/test_permission_policy.py`  
Run: `.venv/bin/mypy infrastructure/permissions tests/database/permission_fixtures.py tests/database/test_permission_policy.py`

- [ ] **Step 8: Commit**

```bash
git add infrastructure/permissions tests/database
git commit -m "feat(permissions): resolve scoped PostgreSQL grants"
```

---

### Task 5: Append-only permission decision audit

**Files:**
- Create: `infrastructure/permissions/audit.py`
- Modify: `infrastructure/permissions/__init__.py`
- Create: `tests/database/test_permission_audit.py`

**Interfaces:**
- Consumes: `PermissionAuditRecorder`, `PermissionDecision`, caller-owned `Session`, and `AuditEvent`.
- Produces: `SQLAlchemyPermissionAuditRecorder.record(decision) -> None`.

- [ ] **Step 1: Write a failing sanitized ALLOW audit test**

```python
def test_allow_decision_appends_sanitized_event(db_session: Session, allowed_decision: PermissionDecision) -> None:
    SQLAlchemyPermissionAuditRecorder(db_session).record(allowed_decision)
    event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "PERMISSION_EVALUATED"))
    assert event is not None
    assert event.result is AuditResult.SUCCEEDED
    assert event.data == {
        "decision": "ALLOW", "required_permissions": ["filesystem.read"], "reason_code": "GRANTED"
    }
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/database/test_permission_audit.py::test_allow_decision_appends_sanitized_event -q`  
Expected: import failure because the recorder does not exist.

- [ ] **Step 3: Implement strict event mapping and mandatory flush**

Map `ALLOW` to `AuditResult.SUCCEEDED`; map `DENY` and `ASK` to `AuditResult.DENIED`. Use fixed
event/action/resource names and only decision, sorted required permissions, and reason code in
JSON. Strictly reconstruct the decision, append, and flush; never commit, rollback, or close.

- [ ] **Step 4: Add denial, ASK, leakage, rollback, and append-only tests**

Persist each outcome; include secret/path/SQL markers in nearby objects and exception causes;
assert none appear in event repr or public errors. Prove caller rollback removes the event and
existing append-only protection rejects event update/delete.

- [ ] **Step 5: Implement safe audit failure mapping**

Convert invalid decisions and persistence failures to constant `PermissionAuditError` messages,
without attempting rollback or a compensating audit event.

- [ ] **Step 6: Run focused and neighboring checks**

Run: `.venv/bin/pytest tests/database/test_permission_audit.py tests/database/test_append_only.py -q`  
Run: `.venv/bin/ruff check infrastructure/permissions tests/database/test_permission_audit.py`  
Run: `.venv/bin/mypy infrastructure/permissions tests/database/test_permission_audit.py`

- [ ] **Step 7: Commit**

```bash
git add infrastructure/permissions tests/database/test_permission_audit.py
git commit -m "feat(permissions): append sanitized policy audits"
```

---

### Task 6: Tool registry and executor integration

**Files:**
- Modify: `core/tools/tool.py`
- Modify: `core/tools/registry.py`
- Modify: `core/tools/types.py`
- Modify: `core/tools/executor.py`
- Modify: `core/tools/errors.py`
- Modify: `infrastructure/tools/filesystem.py`
- Modify: `infrastructure/tools/git.py`
- Modify: `infrastructure/tools/__init__.py`
- Modify: `tests/tools/fakes.py`
- Modify: `tests/tools/test_registry.py`
- Modify: `tests/tools/test_default_registry.py`
- Modify: `tests/tools/test_executor.py`
- Modify: `tests/tools/test_filesystem_tools.py`
- Modify: `tests/tools/test_git_tools.py`

**Interfaces:**
- Consumes: `Permission`, `PermissionEngine`, existing registry/audit/tool contracts.
- Produces: `ToolExecutor(registry, audit_recorder, permission_engine)` where only `ALLOW` reaches `Tool.execute()`.

- [ ] **Step 1: Write failing canonical registry tests**

Assert `required_permissions` are strict `frozenset[Permission]`, all three filesystem tools require
only `Permission.FILESYSTEM_READ`, both Git tools require only `Permission.GIT_READ`, and string or
unknown permission definitions fail registry construction safely.

- [ ] **Step 2: Verify RED and migrate tool definitions**

Run: `.venv/bin/pytest tests/tools/test_registry.py tests/tools/test_default_registry.py -q`  
Expected: failures because definitions still contain strings and workspace-specific aliases. Then
change the generic tool contract, descriptors, and five concrete definitions to canonical enums.

- [ ] **Step 3: Write failing executor ALLOW/DENY/ASK tests**

```python
def test_executor_runs_once_only_after_allow(executable_context: ToolExecutionContext) -> None:
    permission_engine = RecordingPermissionEngine(PermissionOutcome.ALLOW)
    tool = CountingTool()
    result = asyncio.run(executor(tool, permission_engine).execute("fake_read", {}, executable_context))
    assert result.status is ToolResultStatus.SUCCEEDED
    assert tool.calls == 1
    assert permission_engine.calls == 1
```

Add tests proving `DENY`, `ASK`, unknown permission, policy failure, and permission-audit failure
execute zero times; `ASK` returns `APPROVAL_REQUIRED`; permission failures finish the existing tool
audit safely; unknown/undeclared tools do not call permission evaluation.

- [ ] **Step 4: Verify focused RED**

Run: `.venv/bin/pytest tests/tools/test_executor.py -q`  
Expected: constructor/signature and behavior failures because the executor still reads context
membership directly.

- [ ] **Step 5: Integrate the permission engine and remove runtime authority**

Remove `permission_ids` from `ToolExecutionContext`. After lookup and declared-tool checks, build
one `PermissionRequest` from validated scope plus registered requirements. Map outcomes exactly;
add safe tool error codes `APPROVAL_REQUIRED` and `PERMISSION_AUDIT_FAILED`. Preserve one attempt,
timeout, cancellation, output validation, and tool audit semantics.

- [ ] **Step 6: Add forged-context and regression tests**

Prove `model_copy` cannot inject permissions; AgentProfile permission IDs cannot bypass the engine;
raw arguments never reach permission evaluation/audit; cancellation still propagates immediately;
and all five concrete tools retain path, process, size, and timeout guarantees.

- [ ] **Step 7: Run all tool and permission tests**

Run: `.venv/bin/pytest tests/tools tests/permissions -q`  
Run: `.venv/bin/ruff check core/tools core/permissions infrastructure/tools tests/tools tests/permissions`  
Run: `.venv/bin/mypy core/tools core/permissions infrastructure/tools tests/tools tests/permissions`

- [ ] **Step 8: Commit**

```bash
git add core/tools infrastructure/tools tests/tools
git commit -m "feat(tools): require Permission Engine authorization"
```

---

### Task 7: Real-PostgreSQL end-to-end permission enforcement

**Files:**
- Modify: `tests/database/tool_fixtures.py`
- Modify: `tests/database/test_tool_execution.py`
- Create: `tests/database/test_permission_tool_execution.py`

**Interfaces:**
- Consumes: real migrated PostgreSQL, `SQLAlchemyPermissionPolicy`, `SQLAlchemyPermissionAuditRecorder`, `PermissionEngine`, `SQLAlchemyToolAuditRecorder`, and `ToolExecutor`.
- Produces: acceptance evidence that persisted grants—not runtime input—control tool execution atomically.

- [ ] **Step 1: Write failing end-to-end ALLOW test**

Create a real project/agent/task/run, persist one active `filesystem.read` grant, execute
`ReadFileTool`, and assert one `PERMISSION_EVALUATED` event precedes successful terminal tool audit.
Assert no source content, relative filename, or absolute temporary root appears in either audit row.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/database/test_permission_tool_execution.py::test_persisted_grant_allows_audited_read -q`  
Expected: failure until the real adapters are composed correctly.

- [ ] **Step 3: Add the complete enforcement matrix**

Cover missing, expired, revoked, cross-project, partial, forged scope, insufficient autonomy,
production `ASK`, unknown/undeclared tools, audit failure, and caller rollback. For every non-ALLOW
case assert the concrete tool executed zero times and terminal records contain stable codes only.

- [ ] **Step 4: Implement only composition/helper corrections required by acceptance tests**

Keep production composition explicit. Do not add a global session, singleton engine, permission
cache, grant mutation service, or Agent loop.

- [ ] **Step 5: Run PostgreSQL and append-only regression suites**

Run: `.venv/bin/pytest tests/database/test_permission_tool_execution.py tests/database/test_tool_execution.py tests/database/test_permission_policy.py tests/database/test_permission_audit.py tests/database/test_append_only.py -q`  
Run: `.venv/bin/ruff check tests/database`  
Run: `.venv/bin/mypy tests/database`

- [ ] **Step 6: Commit**

```bash
git add tests/database
git commit -m "test(permissions): verify PostgreSQL tool enforcement"
```

---

### Task 8: Documentation, checklist, and complete verification

**Files:**
- Create: `docs/permissions.md`
- Create: `docs/adr/0007-database-backed-permission-authority.md`
- Modify: `docs/adr/README.md`
- Modify: `docs/tools.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Documents: public contracts, composition, policy order, scopes, expiry/revocation, autonomy, `ASK`, audit minimization, transaction ownership, and deliberate Phase 8 boundary.

- [ ] **Step 1: Write permission documentation and ADR**

Document a composition example with one caller-owned session shared by policy and both audit
recorders. Record the selected database-authority approach and rejected runtime-context and role
inheritance alternatives. State clearly that Phase 7 provides no permission mutation API and no
approval workflow.

- [ ] **Step 2: Update repository status and only verified Phase 7 boxes**

Update README and AGENTS in English. Mark exactly the eleven Phase 7 permissions and seven Phase 7
checklist items only after tests prove them. Leave every Phase 8 and later checkbox unchanged.

- [ ] **Step 3: Run fresh complete verification**

Run: `.venv/bin/pytest`  
Expected: all tests pass against real PostgreSQL with no warnings.

Run: `.venv/bin/ruff check .`  
Expected: `All checks passed!`

Run: `.venv/bin/ruff format --check .`  
Expected: every file already formatted.

Run: `.venv/bin/mypy .`  
Expected: no issues.

Run: `docker compose exec -T api alembic current`  
Expected: `20260826_0003 (head)`.

Run: `docker compose exec -T api alembic check`  
Expected: no new upgrade operations.

- [ ] **Step 4: Verify container and API health**

Run: `docker compose up -d --build`  
Run: `docker compose ps`  
Run: `curl --fail --silent http://localhost:8000/health`  
Expected: database and API healthy; response `{"status":"ok"}`.

- [ ] **Step 5: Perform scope, secret, contributor, and diff audit**

Run: `git diff --check`  
Run: `git status --short`  
Run: `git diff --name-only phase-6/tool-registry...HEAD`  
Scan tracked Phase 7 changes for high-confidence secret patterns and `Co-Authored-By` trailers.
Confirm no Phase 8 implementation, permission administration API, write/shell/MCP tool, generated
report, raw-content persistence, or `CLAUDE.local.md` is tracked.

- [ ] **Step 6: Commit verified documentation**

```bash
git add README.md AGENTS.md SYNAPSEOS_DEVELOPMENT_CHECKLIST.md docs
git commit -m "docs(permissions): document verified Phase 7 authority"
```

- [ ] **Step 7: Push and open the stacked Pull Request**

Push `phase-7/permission-engine` and open a PR with base `phase-6/tool-registry`. Include test,
Alembic, Docker, security, and scope evidence. Do not merge or start Phase 8.
