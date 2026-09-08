# Security Agent V1

Phase 18 adds one independent, bounded Security Agent and one explicit persistent workflow stage.
It reviews only caller-supplied, validated evidence. It does not execute external scanners, modify
the repository, merge branches, deploy software, or persist prompts and provider responses.

## Contracts and bounds

`SecurityRequest` contains the persisted task and project scope, four distinct Developer,
Reviewer, QA, and Security identities, the active Security profile, task text, acceptance
criteria, a bounded diff, up to 16 affected files, a successful QA result, one to three fresh test
records, an execution context, a deadline, and a correlation ID.

The main bounds are:

- 16,384 UTF-8 bytes for the diff and for each affected file;
- 65,536 aggregate UTF-8 bytes across affected files;
- 64 scanner or public findings;
- 4,096 maximum provider completion tokens;
- 50 KiB maximum provider response;
- 30 seconds maximum provider timeout and 3,600 seconds maximum workflow timeout;
- one scanner call and one provider call, with no implicit retry or fallback provider.

`SecurityResult` returns `PASS`, `WARN`, or `BLOCK`, bounded findings, a metadata-only scanner
summary, uncertainty reasons, a rationale, confidence, and the original correlation ID.

## Evidence and deterministic authority

The injected `SecurityScannerPort` receives a validated request and returns sanitized finding
metadata. Scanner source IDs are trusted only when explicitly configured. The built-in local
secret-pattern source is always deterministic evidence.

The provider receives locally redacted source and structured QA/scanner evidence. Task and source
content are untrusted data. Provider findings remain suspected; provider output cannot
self-confirm a vulnerability or override deterministic QA, test, redaction, or trusted scanner
evidence.

The final gate is deterministic:

- `PASS`: complete, non-truncated, clean evidence with no unresolved uncertainty;
- `WARN`: suspected findings, incomplete evidence, uncertainty, or a provider-only concern;
- `BLOCK`: at least one trusted, confirmed `HIGH` or `CRITICAL` finding.

## Secret handling

Local redaction covers configured secret-like assignments and common credential formats before
provider analysis. Obvious credentials in task metadata are rejected before any provider call.
Scanner metadata and public findings are checked for secret values and source echoes. This is a
bounded application safeguard, not a complete DLP system, so callers must still avoid supplying
sensitive data.

No prompt, raw response, diff, file content, scanner output, or arbitrary provider metadata is
persisted automatically. Errors expose stable codes and safe messages only.

## Read authority

`SQLAlchemySecurityPermissionPolicy` provides deny-by-default authority for exactly five
low-risk read capabilities:

| Tool | Required permission |
| --- | --- |
| `read_file` | `filesystem.read` |
| `list_files` | `filesystem.read` |
| `search_text` | `filesystem.read` |
| `git_status` | `git.read` |
| `git_diff` | `git.read` |

Authorization requires a running persisted Security `AgentRun`, an active Security agent with
autonomy level 0 or 1, the exact `WAITING_SECURITY` task and project, a distinct active Developer
assignee, and an active matching global or project grant. Unknown tools, altered risk or permission
sets, revoked or expired grants, production access, writes, shell access, self-review, and forged
scope are denied. The policy never commits, rolls back, closes the caller session, or mutates
grants.

The V1 Security Agent still consumes bounded source supplied by the workflow. The permission
policy is the prepared and tested authority boundary for future permissioned repository reads.

## Persistent workflow

`SecurityWorkflowOrchestrator` validates the complete persisted handoff, commits
`SECURITY_STARTED`, invokes Security with no open database transaction, then reacquires and locks
fresh state before the final transition:

| Security decision | Task state |
| --- | --- |
| `PASS` | `COMPLETED` |
| `WARN` | `WAITING_HUMAN` |
| `BLOCK` | `CHANGES_REQUESTED` |

Completion commits `SECURITY_COMPLETED` and `TASK_STATUS_CHANGED` atomically. Timeout, scanner,
provider, persistence, and unexpected failures fail closed through `SECURITY_ESCALATED` and
`WAITING_HUMAN`. Cancellation propagates immediately and does not create a later checkpoint.
Concurrent human transitions win over stale Security work.

Audit payloads use a closed scalar allowlist. They contain decision, confidence, finding counts,
scanner completeness, scanner ID, and safe error codes only. Audit history remains append-only.

## Lifecycle ownership

The caller owns the SQLAlchemy session, scanner, provider, and injected clients. The agent and
workflow do not close injected collaborators. Network resource lifecycle belongs to the provider
adapter or composition root that created it.

## Example composition

```python
policy = SQLAlchemySecurityPermissionPolicy(session)
agent = SecurityAgent(
    provider,
    scanner,
    trusted_source_ids=frozenset({"approved-scanner-suite"}),
    max_tokens=512,
    provider_timeout_seconds=5.0,
)
orchestrator = SecurityWorkflowOrchestrator(session, agent)
result = await orchestrator.run(workflow_request)
```

## Explicit exclusions

Phase 18 does not add Semgrep, Trivy, ZAP, dependency network access, MCP, provider routing,
repository writes, Git branch/commit/PR automation, merge behavior, deployment, reputation,
memory, or Phase 19 functionality.
