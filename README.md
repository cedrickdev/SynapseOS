# SynapseOS

> The operating system for autonomous AI organizations.

[![Status](https://img.shields.io/badge/status-Phase_4-orange)](SYNAPSEOS_DEVELOPMENT_CHECKLIST.md)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Code style: Ruff](https://img.shields.io/badge/code_style-ruff-blueviolet)](https://docs.astral.sh/ruff/)
[![Types: mypy](https://img.shields.io/badge/types-mypy-blue)](https://mypy-lang.org/)
[![License](https://img.shields.io/badge/license-undecided-lightgrey)](#license)

SynapseOS is an **Agentic Software Company Operating System** — a platform that runs a *virtual
software company* of specialised AI agents organised into departments, teams, and roles. A client
submits a specification; the agent organisation scopes it, plans it, chooses technologies, assigns
agents, and builds, reviews, tests, secures, deploys, monitors, and learns from the software.

It is explicitly **not** "a chatbot that codes": it models an organisation with hierarchy,
delegation, independent review, memory, reputation, and governance.

## Table of Contents

- [About](#about)
- [Status](#status)
- [Requirements](#requirements)
- [Getting started](#getting-started)
  - [Run with Docker](#run-with-docker)
  - [Run locally](#run-locally)
- [Project layout](#project-layout)
- [Development](#development)
- [Roadmap](#roadmap)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## About

The platform is built around a few load-bearing ideas:

- **Craft, not technology** — agents are defined by their role (e.g. *Backend Engineer*), not by a
  stack. They load the skills for whatever technologies a project selects.
- **Author ≠ reviewer** — the agent that produces a change never approves it alone.
- **Security has veto power** — an independent security function can block critical risk.
- **Everything is traceable** — every major decision is recorded against evidence, tasks, commits,
  and an immutable audit log.
- **Bounded autonomy** — agent loops always carry stop conditions (max iterations, timeout, budget,
  confidence and escalation rules); irreversible or sensitive actions require a human in the loop.

See [`docs/cahier de charges.md`](docs/cahier%20de%20charges.md) for the full product specification.

## Status

**Phase 4 — LLM provider boundary.** The repository now provides the persistence foundation, an
audited task workflow, and a bounded provider-neutral LLM interface with an Ollama adapter. Runtime
agents, executable tools, skills, MCP, QA
and security engines, and the frontend remain intentionally unimplemented.

What exists today:

- A minimal FastAPI application (`apps/api`) exposing a `/health` liveness endpoint.
- Nine typed SQLAlchemy models covering agents, projects, tasks, executions, decisions, tool-call
  records, score history, and audit history.
- A reviewed Alembic migration with PostgreSQL enums, JSONB, constraints, indexes, and reversible
  upgrade/downgrade behavior.
- Application-level append-only protection and insert/read-only repositories for `AgentScore` and
  `AuditEvent`.
- A framework-independent `TaskStateMachine` with exhaustive transition rules, atomic audit
  events, and protection against direct persisted status changes.
- Provider-neutral immutable LLM contracts, normalized errors, a bounded Ollama HTTP adapter, and a
  deterministic fake provider that requires no Ollama service in tests.
- A full tooling baseline: `pytest`, `Ruff`, `mypy` (strict), plus `Dockerfile` and
  `docker-compose.yml` for the API + PostgreSQL.

Progress is tracked in [`SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`](SYNAPSEOS_DEVELOPMENT_CHECKLIST.md).

## Requirements

- Python **3.12+**
- [`uv`](https://docs.astral.sh/uv/) (recommended) for local environment management
- Docker + Docker Compose — to run the API together with PostgreSQL 16

## Getting started

Copy the example environment file first (never commit real secrets — `.env` is git-ignored):

```bash
cp .env.example .env
```

### Run with Docker

Brings up the Platform API and PostgreSQL together:

```bash
docker compose up --build
```

- API: <http://localhost:8000>
- Health check: <http://localhost:8000/health> → `{"status": "ok"}`
- PostgreSQL host port: `55432` by default (container-to-container traffic remains on `5432`)

### Run locally

Without Docker, using a project virtualenv:

```bash
make venv        # create a Python 3.12 virtualenv (via uv)
make install     # install the project + dev dependencies
make dev         # run the API with autoreload on http://localhost:8000
```

## Project layout

```text
apps/api/                 # FastAPI application (Platform API)
core/                     # Domain layer (placeholders filled in later phases)
  agents/ tasks/ runtime/ memory/ skills/ tools/ scoring/ permissions/
  config.py               # Application settings (env-driven)
infrastructure/           # Adapters to the outside world
  database/               # SQLAlchemy models, sessions, repositories, and append-only guard
  llm/                    # Ollama and deterministic fake LLM adapters
  git/                    # Placeholder for a later phase
alembic/                  # Versioned PostgreSQL migrations
tests/                    # Unit and real-PostgreSQL integration tests
docs/adr/                 # Architecture Decision Records
```

## Development

All routine commands are exposed through the `Makefile`:

```bash
make test        # run the test suite (pytest)
make lint        # lint with Ruff
make format      # format with Ruff
make typecheck   # type-check with mypy
make check       # lint + typecheck + tests
make migrate     # upgrade the configured database to Alembic head
make migration-current    # show the current migration revision
```

Run `make help` to list every available target.

**Working agreement:** changes are test-driven (write the failing test first), and `make check`
must pass before any task is considered done.

## Roadmap

Development proceeds strictly **one phase at a time** — each phase is a single, independently
validated pull request. The near-term sequence is:

1. **Repository initialization** — completed
2. **Fundamental data model** — completed
3. **Task state machine** — completed
4. **LLM provider abstraction (Ollama first)** — *current*
5. Agent core
6. Tool registry

The complete phased plan (up to a full engineering organisation) lives in
[`SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`](SYNAPSEOS_DEVELOPMENT_CHECKLIST.md).

## Documentation

- **Product / organization specification:** [`docs/cahier de charges.md`](docs/cahier%20de%20charges.md)
- **Task workflow:** [`docs/task-state-machine.md`](docs/task-state-machine.md)
- **LLM providers:** [`docs/llm-providers.md`](docs/llm-providers.md)
- **Architecture decisions (ADRs):** [`docs/adr/`](docs/adr/)
- **Repository working agreement:** [`AGENTS.md`](AGENTS.md)

## Contributing

Contribution workflow (formal `CONTRIBUTING.md`, `SECURITY.md`, and `CODEOWNERS` will be added as
part of the Git governance phase):

- One phase = one clear objective = one pull request = one validation.
- Never implement more than one phase at a time, and never add features from a future phase early.
- Write tests first; keep the architecture modular; run `make check` before opening a PR.
- Author and reviewer are always different.
- Never commit secrets. Never grant unbounded system permissions to agents.

## License

**Undecided.** The license (AGPL-3.0 vs Apache-2.0, with possible dual licensing) is an owner-level
governance decision and will be recorded as an ADR before any public release. Until then, no open
source license is granted. See [`docs/adr/`](docs/adr/).
