# Phase 19 Git Workflow Design

## Scope

Phase 19 introduces a bounded, provider-neutral `GitWorkflow` that lets SynapseOS agents work in
one managed local repository through dedicated task branches, commits, status, diffs, history,
pull-request preparation, and deterministic merge-requirement validation.

The implementation is local Git only. It does not connect to GitHub or GitLab, push or fetch,
create a remote pull/merge request, approve a pull request, merge branches, manage CODEOWNERS,
configure remote branch protection, run CI, deploy, or implement any Phase 20 persistence or API.
`prepare_pull_request` returns an immutable local preparation record only. Phase 20 remains
deliberately unimplemented.

The feature must preserve the company constitution: one task branch, least privilege, no secrets
in Git, no hidden failures, no author self-approval, deterministic checks over self-assessment,
protected critical branches, bounded execution, complete auditability, and immediate cancellation.

## Architectural choice

Create an application-level Git workflow boundary in `core/git_workflow/` and one local adapter in
`infrastructure/git/`. Keep it separate from:

- `infrastructure/workspaces/git.py`, which imports repositories into managed workspaces;
- `infrastructure/tools/git.py`, which exposes low-risk read-only `git_status` and `git_diff`
  tools to agents;
- the future Phase 20 pull-request domain model and remote provider integrations.

The core workflow owns validation, authorization rules, operation ordering, safe public results,
and audit orchestration. The local adapter owns exact Git process execution and parsing. This keeps
the contract suitable for future GitHub/GitLab providers without making SynapseOS depend on their
authentication, APIs, branch rules, or metadata.

```text
core/git_workflow/
├── __init__.py
├── audit.py
├── errors.py
├── ports.py
├── types.py
├── validation.py
└── workflow.py

infrastructure/git/
├── __init__.py
├── audit.py
├── local.py
└── policy.py
```

Git-workflow-specific enums remain in `core/git_workflow/types.py`. `core/enums.py` remains
reserved for values shared across several domains or persisted by the common data model.

## Core contracts

All public contracts are strict, immutable Pydantic models with forbidden unknown fields. Every
string, collection, command result, diff, history page, path list, and audit payload has a finite
bound. Exact canonical nested model types are required so mutable subclasses or forged model-like
objects cannot widen authority.

`GitWorkflowContext` contains:

- canonical managed workspace root;
- project UUID;
- task UUID;
- actor agent UUID and stable logical actor identifier;
- actor role;
- optional agent-run UUID;
- correlation UUID;
- finite operation timeout.

The context contains no credentials, environment mapping, executable path, command arguments,
provider configuration, arbitrary metadata, or caller-supplied audit fields.

The local adapter implements a `GitProvider` protocol with exactly the operations required by the
workflow. The protocol consumes validated core requests and returns structured bounded results. It
does not expose a generic command method, arbitrary Git arguments, environment variables, remote
URLs, credential helpers, callbacks, or process handles.

## Task branch model

Phase 19 supports exactly three task branch kinds:

```text
feature/<task-id>-<slug>
fix/<task-id>-<slug>
chore/<task-id>-<slug>
```

The `<task-id>` component is the canonical lowercase UUID string of the persistent task. The slug:

- is lowercase ASCII;
- contains only letters, digits, and single hyphens;
- starts and ends with a letter or digit;
- has a strict finite length;
- cannot contain consecutive separators, dots, slashes, whitespace, reflog syntax, lock suffixes,
  control characters, or Git revision metacharacters.

The full branch name is derived by SynapseOS and never accepted as an arbitrary caller-controlled
reference. Validation also applies `git check-ref-format --branch` through the provider before any
mutation.

`create_task_branch` requires:

- the actor role to be exactly `Developer`;
- a managed Git workspace whose current branch is a configured protected base branch;
- a clean index and worktree, including untracked files;
- no existing local branch with the derived name;
- no detached HEAD, merge, rebase, cherry-pick, revert, or bisect in progress.

It creates and switches to the branch from the current protected base exactly once. It never
deletes, resets, rebases, merges, pushes, fetches, or force-updates a reference. Existing task
branches are rejected rather than reused implicitly.

Protected branch names are an immutable exact allowlist configured by the application. V1 defaults
to `main` and `production`. Prefix matching is not used. No operation in Phase 19 can commit while
checked out on a protected branch.

## Commit model

`commit_changes` is available only to a validated `Developer` on the exact branch derived for the
same task. It accepts:

- one conventional commit kind: `feat`, `fix`, `test`, `docs`, `refactor`, `perf`, `build`,
  `ci`, or `chore`;
- an optional validated lowercase scope;
- one non-empty bounded summary with no newline or control character;
- one through a finite maximum of explicit normalized workspace-relative paths;
- one canonical Git identity supplied by trusted application composition.

The workflow renders the commit subject itself. It does not accept a complete raw commit message,
message file, editor, trailer list, author date, committer date, signing option, amend flag, parent,
tree, or arbitrary Git configuration.

The Git identity contains a bounded display name, service-account email, and logical SynapseOS
agent identifier. The adapter applies name and email through command-local configuration only and
never modifies repository, global, or system Git configuration. The logical agent identifier is
recorded in append-only audit metadata; it is not emitted as an AI co-author trailer.

Before staging, the provider requires an initially clean Git index. It stages only the validated
explicit paths with pathspec separation. Unrelated worktree files are never staged. It obtains a
bounded staged patch with external diff and text conversion disabled, and passes it to an injected
`GitCommitPolicy`.

The V1 policy fails closed when:

- the staged patch is empty or truncated;
- a selected path is outside the workspace, absolute, duplicated, a symlink escape, `.git`, or
  otherwise unsafe;
- the patch contains an obvious confirmed secret according to the existing bounded local secret
  sanitizer;
- the repository enters a conflicting operation state;
- a selected file cannot be represented within the finite inspection budget.

If validation or commit fails after staging, the adapter restores only the selected index entries
to their pre-operation state while preserving worktree contents. It does not use `reset --hard`,
checkout user files, clean untracked files, stash, or delete data. Failure to compensate is surfaced
as an explicit sanitized integrity error and audited; it is never hidden or retried.

The commit runs exactly once with hooks disabled by a command-local empty hooks path, signing
disabled, no editor, no pager, and no inherited credentials. Empty commits, amend, merge commits,
and author self-approval metadata are unavailable by construction.

## Read operations

`get_status` returns structured bounded repository state including:

- current branch or detached state;
- clean/dirty state;
- staged, unstaged, and untracked counts;
- merge/rebase/cherry-pick/revert/bisect flags;
- truncation state.

It does not expose absolute paths, environment values, repository configuration, remote URLs, or
credential information.

`get_diff` supports only approved local comparisons needed by Phase 19:

- worktree against index;
- index against `HEAD`;
- current task branch against one configured protected base.

Optional path filters are normalized through the managed-workspace path resolver. Output uses
stable `a/` and `b/` prefixes, disables color, external diff, text conversion, submodule recursion,
and binary payloads, and reports truncation explicitly. An oversized or truncated diff may be read
but cannot support commit or merge validation.

`get_history` returns at most a fixed finite number of first-parent commit summaries from the
current task branch. Each item contains only commit SHA, parent SHAs, bounded subject, author display
name, and authored timestamp. It excludes commit bodies, email addresses, signatures, notes, raw
log formatting, arbitrary revisions, and patch content. Pagination is explicit and bounded by a
validated non-negative offset and limit.

All three read operations are audited because the Phase 19 requirement covers every Git action.

## Pull-request preparation abstraction

`prepare_pull_request` creates a local immutable `PullRequestPreparation`; it does not create or
persist a `PullRequest` entity. It requires:

- exact task branch checked out;
- configured protected base branch;
- clean index and worktree;
- at least one task-branch commit ahead of the base;
- base to be an ancestor of the task branch;
- no merge commit in the task branch range;
- complete non-truncated local diff and history summaries.

The result contains only:

- project and task UUIDs;
- correlation UUID;
- base and head branch names;
- head commit SHA;
- bounded generated title and summary;
- changed relative paths;
- insertions, deletions, and commit count;
- author logical identifier;
- deterministic preparation checksum.

It contains no provider URL, remote PR number, approval, reviewer decision, QA report, Security
report, credentials, raw patch, prompts, or arbitrary metadata. The checksum binds the stable local
preparation fields so later phases can detect stale or substituted preparations.

## Merge-requirement validation

`validate_merge_requirements` is a read-only deterministic gate. It never merges or updates a Git
reference. It accepts one canonical `PullRequestPreparation` plus bounded evidence references for:

- independent reviewer approval;
- successful QA decision;
- successful Security decision;
- required deterministic check completion.

Evidence contains identifiers and final statuses only, not raw reports. Phase 19 does not create,
store, or approve a pull request. It verifies:

- preparation checksum and project/task/correlation scope;
- current head SHA still matches the preparation;
- head is the exact task branch and is not protected;
- base is protected and still an ancestor of head;
- repository is clean and has no operation in progress;
- task branch contains no merge commits;
- author and reviewer logical identities are different;
- reviewer status is approved;
- QA status is `PASS`;
- Security status is `PASS`;
- every required check is successful and non-truncated;
- all evidence refers to the same project, task, head SHA, and correlation.

The result is `PASS` or `BLOCK` with a bounded tuple of stable reason codes. Missing, stale,
contradictory, malformed, truncated, or uncertain evidence always blocks. There is no `WARN` path
that silently allows a merge.

## Local Git process boundary

The local provider receives one canonical absolute Git executable during trusted composition. Each
operation uses `asyncio.create_subprocess_exec`; no shell is involved. Every command:

- uses an explicit argument tuple assembled by the adapter;
- runs in the canonical managed workspace;
- receives `stdin=DEVNULL`;
- has bounded stdout and stderr drains;
- has a mandatory timeout no greater than the request deadline;
- is executed exactly once with no retry or fallback;
- terminates and then kills the process if timeout or cancellation requires cleanup;
- propagates cancellation immediately after cleanup;
- uses a minimal environment with `PATH`, locale, `GIT_TERMINAL_PROMPT=0`, disabled system/global
  configuration, disabled credential helpers, disabled pager, and disabled optional locks where
  appropriate;
- never inherits tokens, SSH agent variables, askpass helpers, proxy credentials, or user Git
  configuration.

The provider supports no network operations. Its command allowlist contains only the exact local
subcommands and flags needed for Phase 19. No caller can add flags, revisions, pathspec magic,
configuration keys, executable paths, or environment variables.

Stdout and stderr are treated as untrusted. Public errors contain only a stable error code,
sanitized operation name, and optional safe scalar accounting. Raw process output, paths, Git
configuration, commit message content, diff content, and environment data never enter exceptions
or audit events.

## Audit model

Every attempted action is recorded through a `GitAuditRecorder` port backed by PostgreSQL
`AuditEvent`. No schema migration is required. Audit events are append-only and use the shared
correlation UUID.

Each operation commits a `GIT_OPERATION_STARTED` event before Git execution and exactly one of:

- `GIT_OPERATION_COMPLETED`;
- `GIT_OPERATION_FAILED`.

The session is caller-owned and never closed. No database transaction remains open while a Git
process is running. If the start audit cannot be committed, Git is not invoked. If terminal audit
fails after a Git action, the workflow raises an explicit sanitized audit error and leaves the
unmatched start event as durable reconciliation evidence. It never repeats the Git action. A
cancelled invocation stops its process and re-raises cancellation without performing another
database operation; the unmatched start event is the durable cancellation/reconciliation signal.

Audit metadata is an exact scalar allowlist:

- action;
- project, task, actor, run, and correlation identifiers;
- branch kind and derived branch name;
- protected-base name;
- commit SHA after a successful commit;
- selected-path count, changed-path count, commit count, insertion/deletion counts;
- status/result and stable reason/error code;
- output-byte accounting and truncation flags;
- preparation checksum;
- merge-requirement decision and reason codes.

Audit events never contain raw diffs, file contents, path names, commit summaries, author email,
process output, exceptions, configuration, remote URL, credentials, prompts, provider responses,
or arbitrary metadata.

## Failure and concurrency rules

`GitWorkflow` serializes every operation per canonical workspace through an injected process-local
lock registry. This conservative V1 rule prevents reads from observing a half-completed index or
reference mutation. Phase 19 does not claim distributed locking across multiple SynapseOS
processes. The limitation is explicit; future orchestration must ensure one active mutable
workspace owner.

Every mutating request captures the initial branch and head SHA, rechecks them immediately before
mutation, and validates the resulting branch/head after success. Concurrent or out-of-band changes
produce a stale-state error; they are never overwritten.

There is no implicit retry, duplicate Git call, speculative execution, hidden fallback, force
operation, automatic conflict resolution, automatic commit, automatic PR creation, or automatic
merge. Cancellation and timeout never trigger a later audit completion or additional Git action.

All public exceptions clear retained tracebacks from sensitive operation-local data before crossing
the boundary. Results and the workflow instance retain no diff, history, file content, commit
message, subprocess output, or request history after the invocation returns.

## Authorization rules

Phase 19 is an application-level boundary and does not replace PostgreSQL permission grants or the
existing tool permission engine.

- `create_task_branch` and `commit_changes` require exact active Developer identity and
  `git.write` authority supplied by trusted composition.
- `get_status`, `get_diff`, `get_history`, and `prepare_pull_request` require `git.read`.
- `validate_merge_requirements` is read-only and requires `git.read`.
- no actor may operate outside the exact project, task, workspace, and correlation scope;
- no Developer may provide or manufacture reviewer approval;
- no Phase 19 operation grants permission, changes autonomy, or accesses production.

The workflow validates immutable authority declarations before audit or Git side effects. Persisted
permission evaluation remains the responsibility of the existing permission engine at composition
time; Phase 19 never broadens a denied grant.

## Resource and security invariants

- History and in-memory operation state are bounded to one invocation.
- Every command output and public result has an explicit maximum serialized size.
- Every process call and full workflow operation has a mandatory timeout.
- No retry, fallback, duplicated call, or speculative operation exists.
- Cancellation is propagated immediately after bounded process cleanup.
- No prompt, response, raw patch, file content, process output, or secret is persisted.
- No sensitive value appears in public errors or audit metadata.
- Git metadata is filtered through exact typed fields, never arbitrary provider metadata.
- No network connection is created in Phase 19.
- Injected database sessions and policies remain caller-owned and are never closed.
- Existing user changes outside explicit selected paths are never staged, reverted, cleaned,
  stashed, committed, or deleted.
- `main` and `production` are protected conceptually and cannot be commit targets.
- No force push exists because no push operation exists.

## TDD acceptance scenarios

Implementation follows strict RED, GREEN, REFACTOR cycles. Tests use real temporary local Git
repositories. Audit integration tests use only real PostgreSQL schemas built through Alembic, never
`metadata.create_all()`.

Tests cover:

1. strict immutable bounds for contexts, branch requests, commit requests, identity, status, diff,
   history, preparation, merge evidence, decisions, and audit records;
2. exact task branch derivation and rejection of unsafe slugs, arbitrary refs, protected heads,
   detached state, existing branches, dirty base, and in-progress Git operations;
3. branch creation exactly once without changing repository/global Git configuration;
4. explicit-path commits with Conventional Commit subjects and command-local identity;
5. rejection of empty, truncated, unsafe, secret-bearing, or unrelated staged content;
6. compensation after post-staging failure without losing worktree data or touching unrelated
   paths;
7. bounded structured status, three approved diff modes, safe path filtering, and first-parent
   history pagination;
8. disabled hooks, external diff, text conversion, pager, signing, credentials, inherited config,
   shell interpretation, and network operations;
9. timeout termination, immediate cancellation, no retry, and no duplicated command;
10. immutable local pull-request preparation with stable checksum and no remote side effect;
11. deterministic merge requirement `PASS` only with fresh independent review, QA, Security, and
    complete checks for the same head and scope;
12. fail-closed merge validation for self-review, stale head/base, dirty repository, merge commit,
    missing/failed/truncated evidence, and protected head;
13. append-only start/completed/failed audit chronology with exact allowlisted metadata and an
    unmatched start event after immediate cancellation;
14. audit-start failure preventing Git, terminal-audit failure never retrying Git, and caller-owned
    session lifecycle;
15. end-to-end Developer branch, commit, preparation, and merge validation against a real local
    repository and real PostgreSQL audit store;
16. absence of push, fetch, remote PR/MR creation, merge, branch deletion, reset-hard, checkout of
    files, stash, clean, GitHub/GitLab adapter, Phase 20 model, deployment, or production access.

The final gate is the complete PostgreSQL pytest suite, Ruff lint, Ruff format check, strict mypy,
diff integrity, sensitive-metadata review, and an independent scoped security review.

## Documentation checklist

Add `docs/git-workflow.md`; update `README.md` and `AGENTS.md`; add an ADR for the provider-neutral
local Git workflow boundary; and mark only genuinely implemented and verified Phase 19 checklist
items. Phase 20 and all later checkboxes remain unchanged.
