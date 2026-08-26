# Audited Git Workflow

## Purpose

Prepare small, traceable, independently reviewable repository changes without rewriting history.

## Workflow

1. Inspect branch, status, governing files, and the complete relevant diff.
2. Separate unrelated user changes and preserve all local state outside the task scope.
3. Group verified changes into atomic conventional commits with truthful messages.
4. Recheck the committed diff, tests, author identity, secret patterns, and contributor trailers.
5. Report branch, commits, verification evidence, and remaining review requirements.

## Safety and quality

- Never force-push, discard changes, bypass protection, or include secrets without authorization.
- Never claim checks passed when their deterministic output failed or was unavailable.
- Keep author and reviewer roles distinct and preserve auditability.
- Stop and escalate merge conflicts, destructive operations, sensitive files, or ambiguous ownership.
- Production and irreversible actions require the applicable human approval.
