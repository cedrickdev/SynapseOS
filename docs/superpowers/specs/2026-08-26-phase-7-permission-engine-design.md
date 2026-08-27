# Phase 7 Permission Engine Design

**Date:** 2026-08-26  
**Status:** Approved in conversation  
**Scope:** Phase 7 only

## Objective

Phase 7 replaces the caller-supplied permission membership check from Phase 6 with a
deny-by-default, explainable, audited permission engine. An agent may use a tool only when the
registered tool requires known Phase 7 permissions, the database contains active grants for that
agent and scope, the agent run belongs to the same agent/task/project, and the policy returns
`ALLOW`.

The database is the source of execution authority. Permission identifiers declared on an
`AgentProfile` or supplied in a tool execution context are descriptive inputs and cannot grant
authority. Agents receive no API that creates, edits, revokes, or extends their own grants.

## Included scope

Phase 7 includes:

- the eleven canonical V1 permissions;
- strict immutable permission requests and decisions;
- `AgentPermission` persistence with optional project scope and expiry;
- immutable `ToolPermission` requirements derived from registered tools;
- a provider-neutral `PermissionPolicy` contract;
- a central `PermissionEngine` that validates, evaluates, and audits each decision;
- a SQLAlchemy policy adapter that verifies run scope and resolves active grants;
- `ALLOW`, `DENY`, and non-executing `ASK` outcomes with stable reason codes;
- migration of Phase 6 filesystem tools to canonical `filesystem.read`;
- integration with `ToolExecutor` before tool input validation or execution;
- append-only permission decision audit events with allowlisted metadata;
- unit tests and real-PostgreSQL integration tests built through Alembic.

## Explicit exclusions

Phase 7 does not include:

- a permission administration API, dashboard, CLI, or agent-accessible grant method;
- an approval workflow or approval token that can turn `ASK` into `ALLOW`;
- role templates, department inheritance, wildcard permissions, capability bundles, or delegation;
- automatic reputation, seniority, or confidence-based permission changes;
- PostgreSQL RLS, database roles, triggers, or production credential enforcement;
- write, shell, test, network, database, or deployment tools;
- Agent runtime orchestration, skills, MCP, workspace management, retries, or Phase 8 behavior.

The enum contains permissions for later tools, but this phase does not implement those tools.

## Approaches considered

### Database-backed source of authority — selected

Resolve permissions from persisted `AgentPermission` rows after verifying the complete execution
scope. This prevents an agent or caller from gaining authority by modifying a runtime profile or
request object and supports expiry, project scoping, and audit reconstruction.

### Execution-context membership only — rejected

Keeping `permission_ids` in `ToolExecutionContext` as authority would be small, but the set is
caller-provided and therefore forgeable. It cannot satisfy “agents must never grant themselves a
permission.”

### Role templates plus persisted overrides — deferred

Role inheritance would reduce grant administration for a mature company model, but introduces
precedence, revocation, department scope, and policy migration before any permission administration
workflow exists. Explicit grants are safer and sufficient for Phase 7.

## Architecture

```text
Caller
  -> ToolExecutor
     -> begin ToolCall audit
     -> ToolRegistry lookup
     -> declared-tool check
     -> PermissionEngine.evaluate(request)
        -> validate known Permission values
        -> SQLAlchemyPermissionPolicy.evaluate(request)
           -> verify agent/run/task/project scope
           -> load active global + project AgentPermission grants
           -> apply autonomy and approval policy
        -> PermissionAuditRecorder.record(decision)
     -> execute only when decision is ALLOW
     -> finish ToolCall audit
  -> ToolResult or propagated cancellation
```

`PermissionEngine` lives in core and imports neither SQLAlchemy nor tool adapters. The SQLAlchemy
policy and audit recorder live in infrastructure. The executor receives the permission engine as an
injected dependency and owns none of its resources.

## Module boundaries

```text
core/permissions/
├── __init__.py       public Phase 7 API
├── types.py          Permission, request, decision, outcomes, reason codes
├── errors.py         sanitized permission boundary errors
├── policy.py         PermissionPolicy and grant-resolution contracts
├── audit.py          permission audit port
└── engine.py         validation, policy invocation, and mandatory audit

infrastructure/permissions/
├── __init__.py       concrete adapter exports
├── policy.py         SQLAlchemy scope/grant resolver
└── audit.py          append-only AuditEvent recorder

infrastructure/database/models/
└── organization.py   AgentPermission ORM model and relationships
```

The canonical `Permission` enum is genuinely shared by persistence, tools, agents, and policy, so
it belongs in `core/enums.py`. Permission-specific outcomes and reason codes remain in
`core/permissions/types.py` because they are not persisted as PostgreSQL enum columns.

## Canonical permissions

The persisted enum names are uppercase Python identifiers with the following lowercase values:

```python
class Permission(StrEnum):
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    GIT_READ = "git.read"
    GIT_WRITE = "git.write"
    SHELL_EXECUTE = "shell.execute"
    TESTS_EXECUTE = "tests.execute"
    NETWORK_ACCESS = "network.access"
    DATABASE_READ = "database.read"
    DATABASE_WRITE = "database.write"
    DEPLOYMENT_STAGING = "deployment.staging"
    DEPLOYMENT_PRODUCTION = "deployment.production"
```

Unknown identifiers never degrade to strings. Direct engine evaluation returns an audited `DENY`
with reason `UNKNOWN_PERMISSION`; persisted unknown values are rejected by PostgreSQL and strict
model validation.

Phase 6 permission names are normalized as follows:

| Tool | Phase 7 requirement |
|---|---|
| `read_file` | `filesystem.read` |
| `list_files` | `filesystem.read` |
| `search_text` | `filesystem.read` |
| `git_status` | `git.read` |
| `git_diff` | `git.read` |

Listing and literal search are forms of filesystem read authority rather than separate V1
permissions. No compatibility alias is accepted after migration because aliases create ambiguous
authority.

## Persistence model

`AgentPermission` is the materialized source of active permission grants:

- `id`: UUID primary key;
- `agent_id`: required foreign key to `agents`, `RESTRICT` on delete;
- `permission`: required PostgreSQL `permission` enum;
- `project_id`: nullable foreign key to `projects`, `RESTRICT` on delete;
- `granted_by_actor_type`: required existing `AuditActorType`;
- `granted_by_actor_id`: required bounded identifier;
- `reason`: required bounded text;
- `expires_at`: nullable timezone-aware timestamp;
- `revoked_at`: nullable timezone-aware timestamp;
- `created_at`: UTC timestamp.

Database constraints require:

- `granted_by_actor_type <> AGENT` so an agent-authored grant cannot be persisted;
- `expires_at IS NULL OR expires_at > created_at`;
- `revoked_at IS NULL OR revoked_at >= created_at`;
- one global row per `(agent_id, permission)` where `project_id IS NULL`;
- one project row per `(agent_id, project_id, permission)` where `project_id IS NOT NULL`.

Indexes support lookup by `(agent_id, project_id, permission)`, expiry, and active/revoked state.
An active grant has `revoked_at IS NULL` and `expires_at IS NULL OR expires_at > evaluation_time`.
Global and matching-project grants are unioned; grants for another project never apply.

Phase 7 intentionally provides read-only permission repositories and policy adapters. Tests and
migrations may construct rows directly, but normal agent-facing code has no grant, update, delete,
or revoke operation. A future human-governed administration phase will own mutation workflows and
their separate audit requirements.

## Core value objects

### ToolPermission

`ToolPermission` is a strict frozen mapping of a validated tool name to a non-empty bounded set of
canonical `Permission` values. It is derived from the immutable registered tool definition, never
from invocation arguments or an agent response.

Concrete `Tool.required_permissions` and exposed `ToolDefinition.required_permissions` become
`frozenset[Permission]`. Registry construction rejects strings, unknown values, mutable sets, and
empty requirements with a sanitized `ToolDefinitionError`.

### PermissionRequest

The request is strict and frozen and contains only authorization-relevant metadata:

- agent slug, agent run UUID, project UUID, and task UUID;
- registered tool name and risk level;
- immutable required permission identifiers;
- correlation UUID.

It contains no tool arguments, paths, source content, prompts, response data, environment values,
credentials, or database session. The engine accepts raw permission identifiers only at its outer
boundary so it can fail closed and audit `UNKNOWN_PERMISSION`; validated policy adapters receive
canonical enum values only.

### PermissionDecision

The immutable decision contains:

- `outcome`: `ALLOW`, `DENY`, or `ASK`;
- canonical required permissions when valid;
- stable `reason_code`;
- a bounded constant-safe message;
- correlation and execution-scope identifiers;
- evaluation timestamp.

It does not expose all grants held by an agent, grantor identity, expiry values, internal SQL
errors, or policy implementation details.

## Policy semantics

Evaluation is deterministic and deny-by-default. Rules are applied in this order:

1. malformed request or unknown permission → `DENY / UNKNOWN_PERMISSION`;
2. unknown tool, undeclared tool, or invalid execution scope remain executor-level denial reasons;
3. agent/run/task/project mismatch or missing row → `DENY / INVALID_SCOPE`;
4. no active matching grant for every requirement → `DENY / MISSING_PERMISSION`;
5. any `deployment.production` requirement → `ASK / HUMAN_APPROVAL_REQUIRED`;
6. insufficient autonomy for a granted permission → `ASK / AUTONOMY_APPROVAL_REQUIRED`;
7. otherwise → `ALLOW / GRANTED`.

Minimum autonomy levels follow specification §40:

| Permission | Minimum autonomy |
|---|---:|
| `filesystem.read`, `git.read`, `database.read` | 0 |
| `filesystem.write`, `tests.execute` | 1 |
| `git.write` | 2 |
| `network.access`, `shell.execute`, `database.write`, `deployment.staging` | 3 |
| `deployment.production` | 4 plus mandatory human approval |

The table is policy, not an implied permission grant. Both an active grant and sufficient autonomy
are required. Phase 7 has no approval artifact, so `ASK` is terminal and non-executing. It is
returned to callers as a denied tool result with safe code `APPROVAL_REQUIRED`.

The policy performs no retry, fallback, network call, cache, implicit grant, wildcard match, or
permission inference from role names.

## Tool executor integration

`ToolExecutionContext.permission_ids` is removed as execution authority. The executor creates a
permission request only after successful registry lookup and declared-tool validation. It passes
the registered definition’s immutable requirements to `PermissionEngine`.

The order preserves Phase 6 guarantees:

1. validate context and invocation shape;
2. begin mandatory `ToolCall` audit before lookup;
3. deny unknown or undeclared tools without policy access;
4. evaluate and audit permission policy;
5. execute only for `ALLOW`;
6. map `DENY` to `PERMISSION_DENIED` and `ASK` to `APPROVAL_REQUIRED`;
7. continue strict input validation, one attempt, timeout, cancellation, bounded output, and
   terminal tool audit unchanged.

A policy or permission-audit infrastructure failure fails closed with `PERMISSION_AUDIT_FAILED`;
the tool never executes. The executor never substitutes stale profile permissions.

## Permission audit

Every completed policy evaluation appends one `AuditEvent` before tool execution:

- actor type `AGENT` and the validated agent slug;
- project, task, run, and correlation IDs;
- event type `PERMISSION_EVALUATED`;
- action `authorize_tool`;
- resource type `TOOL` and registered tool name;
- result `SUCCEEDED` for `ALLOW`, `DENIED` for `DENY` and `ASK`;
- allowlisted data: decision, sorted required permission values, and stable reason code.

Audit data excludes agent grant inventory, grantor identity, tool arguments, paths, source content,
prompts, exception text, SQL values, environment values, credentials, and absolute host paths.

The SQLAlchemy recorder flushes the append-only event before returning but never commits, rolls
back, or closes the caller-owned session. Audit failure raises a sanitized error and prevents tool
execution. Existing `ToolCall` terminal audit remains separate: permission audit explains why the
decision was made; tool audit records the invocation lifecycle and result.

## Error model

Stable permission reason codes include:

- `GRANTED`;
- `UNKNOWN_PERMISSION`;
- `INVALID_SCOPE`;
- `MISSING_PERMISSION`;
- `HUMAN_APPROVAL_REQUIRED`;
- `AUTONOMY_APPROVAL_REQUIRED`.

Sanitized boundary errors distinguish invalid request, unavailable policy persistence, and failed
mandatory audit without containing rejected values or exception messages. Public tool errors add
`APPROVAL_REQUIRED` and `PERMISSION_AUDIT_FAILED`; neither exposes which unrelated permissions the
agent holds.

## Resource and ownership guarantees

- Permission evaluation is synchronous, local, and bounded to indexed PostgreSQL reads.
- The evaluation timestamp is captured once in UTC and reused for expiry decisions.
- No cache is introduced, preventing stale permission use and invalidation complexity.
- Exactly one policy evaluation and one permission audit event occur per registered, declared tool
  attempt.
- Unknown and undeclared tool attempts retain their existing tool audit but do not query permission
  grants, avoiding capability and grant enumeration.
- Injected policies, recorders, sessions, registries, and tools remain caller-owned.
- No component commits, rolls back, closes, retries, or launches background work implicitly.
- Cancellation behavior after permission evaluation remains immediate and unchanged.

## Database migration

One reversible Alembic revision will:

1. create the PostgreSQL `permission` enum;
2. create `agent_permissions` with its foreign keys, constraints, and indexes;
3. create global and project-scoped uniqueness indexes;
4. downgrade by dropping indexes/table before the enum.

Alembic imports model metadata directly. Tests create schemas only by applying Alembic migrations
to real PostgreSQL; `metadata.create_all()` and SQLite remain forbidden.

## Testing strategy

Strict TDD covers:

- exact enum values and rejection of unknown permissions;
- frozen request, decision, and `ToolPermission` values;
- all policy outcomes and rule precedence;
- deny by default for missing, expired, revoked, cross-project, and partial grants;
- global versus project-scoped grants;
- run/agent/task/project mismatch and forged runtime permissions;
- autonomy thresholds and mandatory production `ASK`;
- proof that an `AGENT` grantor violates a database constraint;
- proof that no engine/repository mutation or self-grant API exists;
- one permission evaluation and audit per eligible invocation;
- no tool execution for `DENY`, `ASK`, unknown permission, invalid scope, policy failure, or audit
  failure;
- successful execution only after `ALLOW`;
- sanitized permission and tool audit rows with no raw content or host data;
- caller-owned transaction rollback removes staged permission/tool audit records;
- migration upgrade, downgrade, re-upgrade, and schema inspection;
- regression coverage for all Phase 6 tools, cancellation, output bounds, and append-only history;
- full pytest, Ruff, mypy, Alembic, Docker, API health, diff, and secret checks.

## Acceptance criteria

Phase 7 is complete only when:

- all eleven permissions exist exactly once as canonical enum values;
- all five Phase 6 tools use canonical permissions;
- permission authority comes from verified active PostgreSQL grants, not runtime input;
- policy returns deterministic, explainable `ALLOW`, `DENY`, or `ASK`;
- only `ALLOW` can reach `Tool.execute()`;
- missing, unknown, expired, revoked, partial, cross-project, and forged authority is denied;
- agents cannot persist grants as their own actor type and no agent-facing grant API exists;
- every policy decision is appended to audit with allowlisted metadata;
- tests use real PostgreSQL schemas created by Alembic;
- complete tests, Ruff, formatting, mypy, Alembic, Docker, and health checks pass;
- only verified Phase 7 checklist boxes are updated;
- Phase 8 remains unimplemented.
