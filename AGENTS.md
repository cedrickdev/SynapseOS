# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Repository status

The repository has completed **Phase 1 — repository initialization** and **Phase 2 — fundamental
data model** and **Phase 3 — task state machine**, and is implementing **Phase 4 — LLM provider
boundary**. It contains a minimal FastAPI
application, typed SQLAlchemy models, Alembic migrations, append-only history protection, an
audited task workflow, bounded provider-neutral LLM contracts, an Ollama adapter, a PostgreSQL
Docker Compose service, and real-PostgreSQL integration tests.

Phase 5 and later phases are not implemented. In particular, there are no autonomous runtime
agents, executable tools, skills, MCP integrations, QA/security engines, provider router, or
frontend. Do not implement work from a later phase unless the user explicitly starts that phase.

Important files:

- **`docs/cahier de charges.md`** — canonical product and organization specification.
- **`SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`** — phased implementation roadmap and acceptance criteria.
- **`README.md`** — project overview, setup, structure, and development workflow.
- **`docs/adr/`** — architecture decision records.
- **`pyproject.toml`** — Python dependencies and pytest, Ruff, and mypy configuration.

Current source layout:

- `apps/api/` — FastAPI application and routes.
- `core/` — domain packages and application configuration.
- `infrastructure/database/` — models, sessions, append-only guard, and repositories.
- `alembic/` — PostgreSQL migrations.
- `tests/` — unit and real-PostgreSQL integration tests.

## Development commands

Use the Makefile targets rather than inventing alternate project commands:

```bash
make venv       # Create the Python 3.12 virtual environment
make install    # Install the project and development dependencies
make dev        # Run the FastAPI development server
make test       # Run the complete pytest suite
make lint       # Run Ruff linting
make format     # Format Python files with Ruff
make typecheck  # Run mypy in strict mode
make check      # Run linting, type checking, and tests
make migrate    # Upgrade PostgreSQL to Alembic head
```

Run a single test with:

```bash
.venv/bin/pytest tests/test_health.py::test_health_returns_200_and_ok_status
```

Docker commands:

```bash
docker compose up --build
docker compose down
```

Docker may not be available in every agent environment. Never claim Docker verification unless the
commands were actually executed successfully.

## Project conventions

- Use English everywhere in source code, comments, docstrings, documentation, branch names, and
  commit messages. Existing French specification and roadmap files remain authoritative inputs and
  do not need translation unless explicitly requested.
- Follow Conventional Commits.
- Do not add AI co-author trailers, including `Co-Authored-By: Claude`, to commits.
- Never commit or push unless the user explicitly requests it.
- Work on one roadmap phase at a time. Do not pre-implement later phases.
- Use test-driven development for features and fixes: observe the failing test before implementing
  the production change.
- Run pytest, Ruff, and mypy before declaring implementation work complete.
- Update checklist boxes only after the corresponding work has been verified.
- Never commit secrets. `.env` files are ignored; `.env.example` contains placeholders only.

## External architectural reference

The local directory `/Users/feze/Downloads/claude-code-master` may be consulted in read-only mode
when implementation work is blocked or when a later roadmap phase needs architectural research on
agent runtimes, tools, permissions, sandboxing, skills, MCP, memory, task execution, concurrency,
code intelligence, or cost tracking.

This directory contains proprietary Anthropic source reconstructed from published source maps. It
is an architectural reference only and is never a dependency or source-code donor for SynapseOS.

Apply a strict clean-room process:

1. Identify the general engineering problem and observable architectural pattern.
2. Restate the requirement using the SynapseOS specification and vocabulary.
3. Prefer public standards and documentation such as MCP, JSON Schema, LSP, and OpenTelemetry.
4. Design an independent Python interface appropriate for SynapseOS.
5. Implement original code without copying source, prompts, comments, tests, internal names, or
   provider-specific behavior.
6. Derive tests exclusively from SynapseOS requirements and public contracts.
7. Record durable architectural choices in SynapseOS ADRs.

Never add the external directory or any of its files to this repository. Never make SynapseOS
depend on Anthropic-specific APIs, authentication, analytics, feature flags, or internal services.
The platform must remain multi-provider, project/company-centric, persistent, auditable, and
human-governed.

Approved concepts that may inform later phases, without expanding the current phase, include:

- a typed tool contract with validation, authorization, execution, risk, timeout, result limits,
  and concurrency classification;
- explainable `ALLOW`, `DENY`, and `ASK` permission decisions;
- safe parallel reads and conservative serialized writes with resource-level locks;
- cancellation, timeout, cleanup, and bounded execution contexts;
- structured lifecycle hooks and audit events;
- versioned skills with provenance, checksums, trust levels, and conditional discovery;
- MCP connection states and capability discovery through public MCP specifications;
- memory limited to non-derivable information and checked for staleness before use;
- future `CodeIntelligenceProvider` implementations for search, LSP, AST, and dependency graphs;
- temporary team scratchpads distinct from validated project and enterprise memory;
- dynamic tool discovery through the future Capability Router;
- skill generation only after independent review and security validation.

These concepts must be introduced only in their designated roadmap phases. In particular, they do
not expand Phase 2 beyond its approved fundamental data model.

The spec is written in **French**, but every product-facing identifier (role names, event names,
task/project states, entity names) is in **English** and must stay English in code. The sections
below are an English distillation so you don't have to re-read ~137 KB of French each session;
`§N` points back to the numbered section in the canonical spec.

## What SynapseOS is

An **Agentic Software Company Operating System**: a platform that runs a *virtual software company*
of specialised AI agents organised into departments, teams, and roles. A client submits a
specification; the agent organisation scopes it (asking classified questions), plans it, chooses
technologies, assigns agents, builds/reviews/tests/secures/deploys the software, monitors it,
collects feedback, and learns from each project. It is explicitly **not** "a chatbot that codes" —
it models an organisation with hierarchy, delegation, independent review, memory, reputation, and
governance.

## Target architecture (Phase 1 foundation implemented)

Runtime topology (§59, §61), request flowing top-to-bottom:

```
Dashboard (UI) → Platform API → Orchestrator
   Orchestrator → Agent Registry · Memory · Event Bus · Capability Router
   Capability Router → MCP Gateway · Local Tools · LLM Router
   MCP Gateway → Git provider · CI/CD · DB · Monitoring · Cloud
   Event Bus → Observability
```

Load-bearing subsystems and the ideas behind them:

- **Orchestrator** — decomposes work, assigns agents, drives the loops. Does *not* micro-manage or
  write all the code itself (the CEO/orchestrator agent explicitly delegates).
- **Agent Registry / internal marketplace** (§45–§47) — agents belong to the *company*, not to a
  project. After closure they return to `AVAILABLE` and are re-selected for new projects, keeping
  their accumulated experience/scores. A scheduler scores candidates against a task's required
  capabilities.
- **Capability Router** (§11) — per task, selects the right skills, MCP servers, and tools;
  enforces permissions; avoids unnecessary/expensive tools (cost-aware, least-privilege).
- **LLM Router** (§35) — picks the model per task by complexity, cost, latency, domain, and
  confidentiality (small model for classification, code model for coding, reasoning model for
  architecture, etc.). Local models (Ollama/llama.cpp/MLX) are in scope.
- **Event Bus** (§52–§53) — departments coordinate through **structured events**
  (`PROJECT_CREATED`, `TASK_ASSIGNED`, `PR_CREATED`, `REVIEW_REJECTED`, `SECURITY_BLOCKED`,
  `DEPLOYMENT_SUCCESS`, `INCIDENT_CREATED`, `CLIENT_APPROVED`, …), **not** free-form chat.
- **Memory** (§14), three tiers: per-agent memory, per-project memory, and an enterprise
  **Knowledge Base** (vector-backed) of validated patterns/anti-patterns/runbooks/lessons.
- **Audit Log** (§54) — immutable; every critical action records actor, project, task, decision,
  confidence, evidence, tools used, result, reviewer, and cost.

Organisational model (§4, §6):

- Hierarchy is **Company → Department → Team → Agent**, used to delegate, arbitrate, and *limit the
  scope of decisions* — not to force every request through many layers.
- Agents are defined by **craft, not technology**: a "Backend Engineer" agent, never a "Laravel
  agent". It loads the skills for whatever stack the project selects (§6.14, §10).
- **Domain agents** (Auth, Payments, Search, Notifications, …) exist only for *significant* domains
  — do not spin up an agent per trivial function (§6.12).
- **Author ≠ reviewer**: the agent that produces a change never approves it alone.
- **Security is an independent department with veto power** over critical risk (§6.5, §28).

## Non-negotiable invariants ("Company Constitution")

These are project-specific hard rules (§25, §28, §39, §40, §65, §66) that any implementation must
enforce — they are the reason the platform exists, not generic advice:

- No known **critical vulnerability** in production; a critical finding can auto-block a merge (§28).
- **No secrets in Git**, and never secrets in prompts or public logs (§27).
- **No hidden failures** — an agent may never conceal a failed test.
- No critical deletion / irreversible or financial action without authorisation.
- Agents must **surface uncertainty**; **deterministic tool results** (tests, linters, scanners,
  builds, metrics) outrank an LLM's self-assessment (§29).
- **Least privilege** everywhere; short-lived credentials; approval gates. Development agents get
  **no** default production access, **no** right to bypass checks, **no** full secret access, and
  **no** ability to disable auditing (§25).
- Every major decision is **traceable** to evidence, tasks, commits, PR/MR, and logs, and recorded
  as an **ADR** (§23).
- **Human-in-the-loop** is mandatory for irreversible actions, spending, sensitive data, low
  confidence, unresolved conflicts, major scope change, and final acceptance (§65).

Permission/autonomy is a 0–5 ladder (§40): 0 read-only → 1 modify code → 2 commit/branch/PR →
3 deploy staging → 4 deploy production → 5 financial/irreversible.

## Core domain model

- **Entities** (§62): Company, Department, Team, Agent, AgentCapability, Skill, Tool, MCPServer,
  Project, ProjectMember, Milestone, Epic, UserStory, Task, TaskDependency, Decision,
  DecisionEvidence, Review, PullRequest, TestRun, SecurityFinding, Deployment, Incident, Feedback,
  ReputationEvent, MemoryEntry, KnowledgeEntry, AuditEvent, CostEvent.
- **Work hierarchy** (§17): Project → Milestone → Epic → UserStory → Task → Subtask.
- **Task states** (§63): DRAFT, READY, ASSIGNED, IN_PROGRESS, WAITING_REVIEW, REJECTED, BLOCKED,
  WAITING_HUMAN, DONE, CANCELLED.
- **Project states** (§64): INTAKE, DISCOVERY, PLANNING, APPROVED, IN_PROGRESS, STAGING,
  CLIENT_REVIEW, COMPLETED, ARCHIVED, PAUSED, CANCELLED.
- **Loop Engineering** (§18–§19): every agent/team/department/company loop is
  Understand → Plan → Act → Observe → Verify → (Fix/Replan | Done) and **must** carry stop
  conditions: max iterations, timeout, minimum-progress threshold, confidence threshold, escalation
  rule, and budget cap. (Runaway loops are risk #1 — §68.)
- **Confidence vs Reputation** (§8) — keep these distinct: *Confidence* is per-decision; *Reputation*
  is an agent's measured history. Overconfidence is penalised via *calibration*. Conceptually
  `Trust = expertise × calibrated confidence × historical reliability × evidence quality ×
  verification result`. Reputation changes autonomy/permissions/seniority and future selection —
  it is not "ML learning". Real model improvement (SFT/DPO/RL) is a separate, deferred pipeline
  fed by validated examples (§43, §6.11.3).

## Build order (where to start)

The spec is emphatic about building incrementally and **not** implementing all departments at once
(over-architecture is risk #6, §68). Guiding principle (Conclusion): *first prove a small group of
agents can collaborate reliably on a real repository, then expand.*

- **V1 agents** (§57): Project Manager/Orchestrator, CTO/Architect, Developer, Reviewer, QA,
  Security, DevOps. V1 flow: intake → classified questions → task decomposition → Git branches/PR →
  tests → independent review → security check → correction loop → confidence → memory → audit →
  staging → completion.
- **Phases** (§58): 0 single-agent prototype → 1 Developer+Reviewer → 2 QA+Security → 3 PM+
  Architecture → 4 multi-domain engineering → 5 memory+reputation → 6 full organisation.
- **V1 success criteria** (§69) define "done" for the first milestone — use them as the acceptance
  checklist.

## Conventions & decisions still open

- **The Phase 1 backend stack is chosen:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2,
  Alembic, PostgreSQL, psycopg 3, pytest, Ruff, mypy, Docker, and Docker Compose. Future stack
  choices such as the event bus, vector store, local LLM runtime, and frontend remain open and must
  be recorded as ADRs when their roadmap phase begins.
- **No license chosen** (Annexe C): AGPL-3.0 vs Apache-2.0, with possible dual licensing — an owner
  decision that must be recorded before any public release.
- **Git governance to define** before opening up: CODEOWNERS, protected branches
  (`feature/*`, `fix/*`, `hotfix/*`, `release/*`; protected `main` and production — §20), commit
  signing, CONTRIBUTING.md, SECURITY.md, versioning/changelog, responsible disclosure.
- **Docs layout** will expand incrementally (§22): `/docs/{architecture, adr, api, security,
  deployment, product, incidents, runbooks, decisions}`. Phase 1 currently provides `docs/adr/`.
