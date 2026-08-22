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
