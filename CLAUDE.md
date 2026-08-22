# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

This repository is **specification-stage**: there is no source code, build system, tests, or
dependency manifest yet — only the product specification (a French *cahier des charges*) and a
one-line README. There is nothing to build, lint, or run today; the only tooling is `git`.

**When the first code lands, replace this section with the real build / test / lint / run commands
(including how to run a single test).** Do not invent commands before then.

Files in the repo:

- **`agentic_company_cahier_des_charges (1).md`** — the canonical, most complete spec. It is the
  source of truth: full department/role cards (§6), vocabulary (§2), RACI (§3.4), runtime
  architecture (§59, §61), data model (§62), state machines (§63–§64), and governance/licensing
  annexes (A–C).
- `cahier_des_charge.md` — an earlier, shorter draft of the same document (§1–§70) with
  less-detailed role definitions and fewer departments. Secondary; prefer the canonical file when
  the two diverge.
- `README.md` — project name and tagline only.

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

## Target architecture (design only — nothing implemented)

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

- **No stack has been chosen.** The technologies in §60 (Python/FastAPI/Pydantic/asyncio; Redis
  Streams/RabbitMQ/NATS/Kafka; PostgreSQL + pgvector; Ollama/llama.cpp/MLX for local LLMs; Nuxt/Vue
  or Next/React dashboard; GitHub/GitLab; Docker) are explicitly *possible, not mandatory*. Record
  the actual choice as an **ADR** before building.
- **No license chosen** (Annexe C): AGPL-3.0 vs Apache-2.0, with possible dual licensing — an owner
  decision that must be recorded before any public release.
- **Git governance to define** before opening up: CODEOWNERS, protected branches
  (`feature/*`, `fix/*`, `hotfix/*`, `release/*`; protected `main` and production — §20), commit
  signing, CONTRIBUTING.md, SECURITY.md, versioning/changelog, responsible disclosure.
- **Docs layout** once code starts (§22): `/docs/{architecture, adr, api, security, deployment,
  product, incidents, runbooks, decisions}`.
