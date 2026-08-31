# Architecture Decision Records (ADR)

This directory holds **Architecture Decision Records**: short, versioned
documents capturing significant technical decisions, their context, the options
considered, and their consequences (cahier des charges §23).

- One decision per file, named `NNNN-kebab-case-title.md` (zero-padded, incrementing).
- Never edit an accepted ADR's decision in place — supersede it with a new ADR and
  update the old one's status to `Superseded by ADR-NNNN`.

## Template

```markdown
# ADR-NNNN — <title>

- **Status:** Proposed | Accepted | Superseded by ADR-XXXX
- **Date:** YYYY-MM-DD
- **Deciders:** <who>

## Context
What is the problem / forces at play?

## Options considered
- Option A — pros / cons
- Option B — pros / cons

## Decision
What we chose and why.

## Consequences
Trade-offs, risks, follow-ups.
```

## Index

- [ADR-0001 — Phase 1 project initialization](0001-phase-1-project-initialization.md)
- [ADR-0002 — Phase 2 fundamental data model](0002-phase-2-fundamental-data-model.md)
- [ADR-0003 — Audited task state machine](0003-phase-3-task-state-machine.md)
- [ADR-0004 — Provider-neutral LLM boundary](0004-provider-neutral-llm-boundary.md)
- [ADR-0005 — Agent runtime boundary](0005-agent-runtime-boundary.md)
- [ADR-0006 — Tool registry execution boundary](0006-tool-registry-execution-boundary.md)
- [ADR-0007 — Database-backed permission authority](0007-database-backed-permission-authority.md)
- [ADR-0008 — Local versioned Skills Registry](0008-local-versioned-skills-registry.md)
- [ADR-0009 — Managed project workspaces](0009-managed-project-workspaces.md)
- [ADR-0010 — Transactional write tools](0010-transactional-write-tools.md)
- [ADR-0011 — Secure command profiles](0011-secure-command-runner.md)
