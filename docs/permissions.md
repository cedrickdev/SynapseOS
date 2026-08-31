# Permission engine

Phase 7 makes PostgreSQL `AgentPermission` rows the sole source of execution authority. Runtime
profiles and tool contexts may describe capabilities, but they cannot grant them. Every registered
tool declares one or more canonical `Permission` enum values, and `ToolExecutor` executes only an
audited `ALLOW` decision.

## Composition

All adapters share one caller-owned SQLAlchemy session so the permission decision, permission
audit, tool call, and terminal tool audit participate in the same transaction:

```python
permission_engine = PermissionEngine(
    SQLAlchemyPermissionPolicy(caller_owned_session),
    SQLAlchemyPermissionAuditRecorder(caller_owned_session),
)
executor = ToolExecutor(
    create_default_tool_registry(),
    SQLAlchemyToolAuditRecorder(caller_owned_session),
    permission_engine,
)
```

None of these components commits, rolls back, closes the session, retries, caches grants, or owns
network resources.

## Decision order

1. Validate the invocation and begin the tool audit.
2. Reject an unknown or undeclared tool without consulting permission policy.
3. Verify the agent slug, run, task, assigned agent, and project as one coherent persisted scope.
4. Resolve every required active global or matching-project grant.
5. Deny missing, partial, expired, revoked, or cross-project grants.
6. Apply the minimum autonomy level after grant verification.
7. Return `ASK` for insufficient autonomy and always for production deployment.
8. Append `PERMISSION_EVALUATED`; only then may an `ALLOW` execute the tool.

`DENY` and `ASK` are terminal and non-executing in Phase 7. There is no approval workflow yet.
Unknown permission identifiers are audited and denied. Agents cannot create their own grants: the
database rejects `AGENT` as a grantor actor type.

## Audit minimization

Permission audit data is allowlisted to the decision, sorted required permission identifiers, and
stable reason code. It excludes arguments, paths, source content, prompts, outputs, exceptions,
credentials, grantor identity, expiry details, and unrelated grants. Permission and tool audits are
separate append-only events linked by execution scope and correlation ID.

## Deliberate boundary

Phase 7 provides the permission enum, persisted grants, policy evaluation, mandatory audit, and
tool enforcement. It intentionally provides no grant administration API, role inheritance,
wildcards, approval workflow, RLS, PostgreSQL triggers, permission cache, write/shell/network/
database/deployment tools, skills, or MCP integration. Those remain later-phase work.
