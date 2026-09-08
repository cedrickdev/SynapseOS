# Git Workflow

Phase 19 provides a bounded, audited, provider-neutral workflow for local Git repositories. It
lets a Developer create one task branch, commit an explicit path set, inspect repository state,
prepare immutable local pull-request metadata, and evaluate deterministic merge requirements.

## Supported operations

| Operation | Mutates Git | Required authority | Result |
| --- | --- | --- | --- |
| `create_task_branch` | Creates and checks out one branch | Developer + `git.write` | Branch name and head SHA |
| `commit_changes` | Stages explicit paths and creates one commit | Developer + `git.write` | Commit metadata |
| `get_status` | No | `git.read` | Structured repository state |
| `get_diff` | No | `git.read` | Bounded local patch metadata |
| `get_history` | No | `git.read` | Bounded first-parent history |
| `prepare_pull_request` | No | Developer + `git.write` | Immutable local preparation |
| `validate_merge_requirements` | No | `git.read` | `PASS` or fail-closed `BLOCK` |

All operations emit append-only `STARTED` and terminal audit records. Trusted composition uses a
session factory and commits each lifecycle event in its own short transaction. The `STARTED` event
is durable before a Git mutation begins; a terminal-audit failure therefore leaves durable
reconciliation evidence and never retries the Git action. Cancellation propagates immediately
after process cleanup and does not fabricate a terminal audit event.

## Branch and commit rules

Task branches are derived internally and have one of these forms:

```text
feature/<task-uuid>-<slug>
fix/<task-uuid>-<slug>
chore/<task-uuid>-<slug>
```

`main` and `production` are conceptually protected. Branch creation requires a clean protected
base, no in-progress Git operation, and no existing derived branch. Commits are allowed only on
the exact branch derived from the active task. SynapseOS renders the Conventional Commit subject,
uses command-local identity, disables hooks and signing, and never adds an AI co-author trailer.

Only caller-selected, normalized workspace-relative paths are staged. The index must initially be
clean. The staged patch is bounded and inspected by the local obvious-secret policy. Failure after
staging compensates the selected index entries while preserving worktree content.

## Pull-request preparation and merge gate

`PullRequestPreparation` is local metadata, not a persisted or remote pull request. Its SHA-256
checksum binds project, task, correlation, protected base name and SHA, task branch and head SHA,
title, summary, changed paths, line counts, commit count, and author logical identifier.

The merge gate is read-only and fail-closed. It requires:

- an unchanged, clean task branch and protected base;
- an ancestor base, no merge commits, and complete non-truncated Git evidence;
- an independent Reviewer approval;
- successful, non-truncated QA and Security evidence;
- all required deterministic checks to pass;
- matching project, task, correlation, and head SHA across every evidence reference.

Missing, failed, stale, contradictory, malformed, or truncated evidence returns `BLOCK` with
stable reason codes. The gate never merges, pushes, fetches, or changes a reference.

## Process and audit safety

The local adapter executes fixed argument vectors with no shell, no retries, no inherited
credentials, no interactive prompt, bounded concurrent stdout/stderr capture, finite timeouts,
process-group termination, and immediate cancellation propagation. The workflow never closes
caller-owned resources; the transactional audit adapter closes only sessions it creates from the
trusted injected factory.

Audit metadata uses a scalar allowlist. It excludes paths, patches, commit summaries, process
output, exception text, credentials, prompts, and arbitrary provider metadata.

The workflow currently uses one process-local lock per composed workflow instance. This safely
serializes operations through that instance but is not a distributed lock. Cross-process locking,
remote providers, GitHub/GitLab APIs, push/fetch/merge, persisted pull requests, branch-protection
APIs, and database-level Git audit enforcement belong to later phases.
