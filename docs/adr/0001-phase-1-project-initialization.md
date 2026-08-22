# ADR-0001 — Phase 1 project initialization

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** Platform Owner (with Claude Code)

## Context

SynapseOS was specification-stage only. Phase 1 of
[`SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`](../../SYNAPSEOS_DEVELOPMENT_CHECKLIST.md)
requires a clean, testable repository foundation ready to host the agentic
runtime — with **no** agentic/LLM/tools/skills/MCP/frontend logic yet. The
mandated stack is Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic,
PostgreSQL, psycopg, pytest, Ruff, mypy, Docker/Compose, and a modular
architecture.

## Options considered & decisions

1. **Build backend — hatchling** (vs setuptools/poetry). Chosen for a minimal,
   PEP 621-native config and simple multi-package mapping.
2. **Package layout — top-level `apps` / `core` / `infrastructure`** (vs a single
   nested `synapseos/` package). Chosen because the Phase 1 prompt lists paths as
   `apps/api`, `core/agents`, … The repository root *is* the project root.
3. **`psycopg` = psycopg 3**, with SQLAlchemy URL scheme `postgresql+psycopg://`.
4. **`/health` is a database-independent liveness probe** returning
   `{"status": "ok"}`. Acceptance only requires HTTP 200; keeping it decoupled
   from PostgreSQL means the endpoint (and its test) need no running database. A
   deeper readiness/DB check can be added in a later phase.
5. **SQLAlchemy engine/session wired, but no ORM models and no Alembic
   migrations.** The engine connects lazily. Models + migrations are explicitly
   Phase 2 work and were deliberately *not* added.
6. **License intentionally unset.** AGPL-3.0 vs Apache-2.0 (or dual licensing) is
   an owner-level governance decision (Annexe C) to be recorded before any public
   release.
7. **Empty `core/*` and `infrastructure/{llm,git}` subpackages** are created as
   documented placeholders (docstring naming the future phase) to establish the
   modular structure without implementing future-phase features.

## Consequences

- `docker compose up` **could not be verified in the build environment** (Docker
  is not installed here). The `Dockerfile` / `docker-compose.yml` are written to
  spec but must be validated on a Docker-capable machine.
- Local verification (pytest, Ruff, mypy) is run against a **Python 3.12**
  virtualenv created with `uv`, matching the target runtime even though the host
  interpreter is newer.
- Non-root user in the container image aligns with the least-privilege invariant
  of the Company Constitution.
