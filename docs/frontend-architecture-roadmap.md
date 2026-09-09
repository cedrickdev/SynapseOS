# SynapseOS — Frontend Architecture & Implementation Roadmap

> **Status:** Architecture decision record and implementation specification — approved design direction, implementation intentionally deferred until the backend/runtime is sufficiently mature.
>
> **Repository target:** `cedrickdev/SynapseOS`
>
> **Intended path:** `docs/frontend-architecture-roadmap.md`
>
> **Core delivery rule inherited from SynapseOS:** **one phase = one clear objective = one PR = one validation**. The frontend must be implemented progressively and must not bypass backend invariants, permissions, state machines, or auditability.

---

## 1. Purpose of this document

This document is the complete frontend architecture specification for SynapseOS. It converts the validated product and technical decisions into a roadmap that can later be executed phase by phase.

It is deliberately more than a technology list. For each major subsystem it records:

- the objective;
- why the technology was selected;
- how it integrates with SynapseOS;
- expected installation/configuration approach;
- target file/folder structure;
- security and architecture rules;
- testing expectations;
- acceptance criteria;
- common failure modes;
- deliberately deferred scope;
- Definition of Done.

This document is also intended to prevent architecture drift. A future implementation should not silently replace a validated technology or weaken a validated invariant without an explicit ADR/update to this specification.

### 1.1 Important sequencing decision

The SynapseOS backend/runtime remains the priority. The frontend must not pressure the backend into premature endpoints, duplicate business rules in the browser, or introduce workarounds around unfinished runtime components.

Frontend implementation begins only when the backend exposes stable enough contracts for the first vertical slices. Mock data may be used during visual prototyping, but mock-only behavior must never be confused with runtime behavior.

### 1.2 Existing backend invariants the frontend must respect

The frontend is a client of the SynapseOS runtime, not a second runtime. In particular:

- task status changes remain controlled by the backend `TaskStateMachine`;
- tool authorization remains controlled by the Permission Engine;
- agent/tool actions remain auditable;
- dangerous operations remain bounded and explicitly authorized;
- the browser never gets direct shell, filesystem, provider-secret, or database authority;
- provider-neutral backend contracts remain provider-neutral in the UI;
- raw runtime evidence may be sensitive and must be redacted/permission-checked before display;
- frontend confidence visualizations must never imply that a confidence score is objective truth.

---

# 2. Product vision: a real company simulator, not a generic dashboard

The frontend must make SynapseOS feel like a living, observable software company operated by AI agents while remaining operationally serious.

The interface therefore has **three complementary modes**.

## 2.1 Company View / Company Simulator

The Company View is the immersive representation of the organization.

Its purpose is to answer quickly:

- Which departments are active?
- Which agents are working?
- What is each agent working on?
- Which tasks are blocked?
- Which review or security gates are waiting?
- Where is a workflow currently moving?
- What changed in the company recently?

The Company Simulator must **never invent activity for entertainment**. Every animation, status, transition, badge, line, packet, warning, or conversation metaphor must map to a real backend state or event.

Examples of valid semantic visuals:

- an available agent appears idle/asleep;
- a working agent appears at a workstation;
- a blocked agent receives a warning state;
- delegation can be visualized as communication between agent nodes;
- a reviewer receiving a dossier maps to a real review request;
- a security stop maps to a real veto/blocked transition;
- a task packet moving between agents maps to a real workflow transition;
- a completed test/pipeline stage changes state only after the real result exists.

Example live sequence:

```text
Backend Agent — implementing task
        ↓
pytest failed
        ↓
corrective loop
        ↓
pytest passed
        ↓
Reviewer Agent
        ↓
changes requested
        ↓
Developer correction
        ↓
review accepted
```

### Agent cards

An agent card may expose, subject to permissions:

- name;
- role;
- department;
- current status;
- current task;
- model/provider identity where allowed;
- confidence value with appropriate caveat;
- current iteration;
- last tool/action;
- elapsed runtime;
- token/cost metrics when available;
- blocking reason;
- last event timestamp.

### Morning Meeting / Daily Briefing

A Daily Briefing may summarize:

- active projects;
- work completed since the previous briefing;
- blocked tasks;
- review backlog;
- QA/security findings;
- provider incidents;
- cost/token anomalies;
- priorities for the current period.

The briefing must be generated from actual system state/evidence. It must not fabricate fictional employee dialogue.

## 2.2 Control Center

The Control Center is the serious administration and operational cockpit.

It covers:

- Projects;
- Agents;
- Tasks;
- Runs;
- Reviews;
- Approvals;
- Providers;
- Tools;
- Skills;
- Permissions;
- Costs/tokens;
- Memory;
- Context Intelligence;
- Notifications;
- Security;
- Audit;
- settings.

The visual language should be dense but readable: compact navigation, strong tables, drawers, filters, obvious statuses, minimal decorative chrome.

## 2.3 Deep Inspect

Deep Inspect is for technical investigation.

It may expose, with strict permission/redaction rules:

- run timelines;
- structured runtime events;
- tool calls;
- command profiles;
- stdout/stderr excerpts;
- traces;
- audit events;
- retry/corrective-loop history;
- model-routing decisions;
- selected context metadata;
- security failures.

Deep Inspect is where xterm-style presentation is appropriate. It must not become an unrestricted shell.

---

# 3. UX identity and navigation

## 3.1 Visual references

The desired level of polish and interaction is inspired by:

- Linear;
- Vercel;
- Supabase;
- GitLab;
- GitHub.

These are references for principles and quality, not templates to copy pixel-for-pixel.

Desired characteristics:

- dark-first;
- neutral surfaces;
- dense but readable information;
- thin borders;
- restrained use of shadow;
- precise typography;
- compact sidebar;
- drawers/panels for detail inspection;
- strong table UX;
- clear states/badges;
- terminal-like technical surfaces;
- excellent keyboard navigation;
- command palette as a first-class navigation surface.

## 3.2 Proposed information architecture

```text
Company
├── Office / Simulator
├── Departments
└── Daily Briefing

Projects
├── All Projects
└── Project Detail

Agents
├── Directory
├── Agent Detail
└── Department Views

Operations
├── Tasks
├── Runs
├── Reviews
└── Approvals

Intelligence
├── Memory
├── Context Intelligence
├── Model Routing
└── Costs / Usage

Security
├── Findings
├── Vetoes
├── Permissions
└── Audit

Administration
├── Providers
├── Tools
├── Skills
├── Artifacts
└── Settings
```

This navigation can evolve, but Company View, Control Center, and Deep Inspect must remain conceptually distinct.

---

# 4. Validated technology stack

## 4.1 Core frontend

- **Nuxt**
- **Vue**
- **TypeScript (strict)**
- **Nuxt UI**
- **Tailwind CSS**

### Why Nuxt instead of Next.js

Nuxt is the validated choice because:

- the backend is already an independent FastAPI system, so Next.js server actions/full-stack coupling is not required;
- SynapseOS is an application/cockpit, not primarily an SEO content site;
- Vue Composition API is well suited to highly interactive stateful surfaces;
- Pinia integrates naturally for application/UI state;
- Nuxt provides a clean application framework around Vue;
- the team/user already has Vue/Nuxt familiarity;
- the frontend remains independently deployable against the provider-neutral Python backend.

Next.js/React has strengths such as ecosystem size, React Flow, and animation libraries, but those strengths do not outweigh the Nuxt fit for this product.

## 4.2 Styling and component layer

- **Nuxt UI** for application primitives;
- **Tailwind CSS** for layout/design freedom.

Vuetify is intentionally not the default because the desired Linear/Vercel/Supabase-style product requires more visual control and less Material-design gravity.

## 4.3 State management

- **Pinia** — client/application/UI state;
- **TanStack Query for Vue** — server state.

Pinia owns things such as:

- authenticated-user UI state that is safe to cache client-side;
- UI preferences;
- selected agent/project where appropriate;
- simulator presentation state;
- temporary filters/layout preferences;
- local interaction state that is genuinely global.

TanStack Query owns remote FastAPI state:

- projects;
- agents;
- tasks;
- runs;
- audits;
- reviews;
- providers;
- permissions;
- artifacts;
- metrics.

**Rule:** do not duplicate the complete API cache into Pinia.

## 4.4 API and contract generation

- FastAPI OpenAPI as backend schema source;
- **Orval** to generate TypeScript types/clients/TanStack Query integration;
- generated code isolated under `api/generated/`;
- application-facing composables/adapters wrap generated code where appropriate.

Generated files are never manually edited.

## 4.5 Communication model

- **REST** for commands, CRUD and explicit request/response interactions;
- **SSE** as the primary server → browser real-time channel;
- **WebSocket only when genuine bidirectional low-latency interaction is required**.

Typical SSE events:

```text
agent.started
agent.completed
agent.failed
agent.blocked
task.status_changed
run.iteration_started
run.iteration_completed
tool.started
tool.completed
tool.failed
review.requested
review.changes_requested
review.approved
security.veto
provider.health_changed
approval.required
pipeline.stage_changed
```

SSE is favored for normal live runtime events because it is HTTP-friendly, simpler operationally, and naturally fits one-way event streaming.

WebSocket is reserved for future use cases such as:

- interactive terminal sessions;
- direct agent chat requiring continuous bidirectional messages;
- live collaborative control surfaces.

## 4.6 Workflow and organization visualization

- **Vue Flow** — primary interactive workflow/company graph engine.

Uses:

- agent nodes;
- department graph;
- workflow state;
- task movement;
- delegation edges;
- review handoffs;
- zoom/pan/selection;
- interactive dependency views when appropriate.

## 4.7 Custom data visualization

- **D3.js** for custom visualizations where a standard chart abstraction is insufficient.

Examples:

- agent heatmaps;
- dependency topology;
- inter-department flows;
- memory/RAG topology;
- decision networks;
- context-flow visualizations;
- specialized cost/usage topology.

D3 must not reinvent Vue Flow.

## 4.8 Standard analytics charts

- **ECharts** for ordinary dashboard analytics.

Examples:

- cost/day;
- tokens/project;
- latency/provider;
- success rate/agent;
- retries;
- tool calls;
- security findings;
- memory hit rate;
- context-compression savings;
- run duration distributions.

Rule of separation:

```text
Vue Flow → workflows/org graphs
D3       → custom/advanced visualizations
ECharts  → standard analytics
```

## 4.9 Motion

- **Motion for Vue** — default UI and semantic micro-animation layer;
- **GSAP** — only for complex synchronized Company Simulator sequences.

Motion for Vue handles:

- panel transitions;
- cards;
- state changes;
- micro-interactions;
- layout transitions.

GSAP is reserved for:

- synchronized multi-agent sequences;
- task packet movement;
- coordinated simulator timelines;
- advanced choreography that would be cumbersome with ordinary transitions.

Animations must remain semantic and respect `prefers-reduced-motion`.

## 4.10 Authentication

- **Authentik**, self-hosted, deployed as part of the infrastructure;
- OIDC/OAuth flow between Nuxt, Authentik and FastAPI.

Target model:

```text
Nuxt
  ↓
Authentik
  ↓ OIDC
FastAPI
  ↓
SynapseOS authorization / Permission Engine
```

Authentik handles identity concerns:

- login;
- MFA;
- password reset;
- sessions;
- users/groups;
- OIDC/SSO.

SynapseOS retains business authorization:

- workspace/project roles;
- agent permissions;
- tool permissions;
- approval rights;
- security veto authority;
- deployment authority;
- workflow transition authority.

**Authentication is not authorization.**

Authentik deployment details are version-sensitive. At implementation time, verify the official deployment architecture/dependencies instead of freezing assumptions (for example, do not add Redis merely because an older deployment guide required it).

## 4.11 Forms and client validation

- **Zod** for client-side schemas/parsing/types;
- **vee-validate** for form lifecycle/state/errors.

Frontend validation improves UX. FastAPI/Pydantic remains authoritative.

## 4.12 Testing

- **Vitest** — unit tests;
- **Vue Test Utils** — component tests;
- **Playwright** — E2E/integration browser tests;
- **axe-core + Playwright** — automated accessibility checks where applicable.

Also required:

- TypeScript strict;
- ESLint;
- consistent formatting via Prettier or the Nuxt ecosystem tooling chosen at bootstrap.

## 4.13 Observability

- **Sentry** — browser error reporting and frontend performance;
- **OpenTelemetry** — distributed correlation across frontend/backend/runtime.

Desired trace chain:

```text
Nuxt
→ FastAPI
→ Orchestrator
→ Agent
→ Tool
→ LLM
→ Reviewer
```

Observability must not capture secrets, provider tokens, unredacted prompts, sensitive file content or unrestricted raw outputs.

## 4.14 Terminal / raw logs

- **xterm.js** for technical terminal/log-like views.

Two concepts must remain separate:

- **Run Timeline** — structured, readable runtime events;
- **Terminal / Raw Logs** — lower-level stdout/stderr/command evidence.

xterm.js is not permission to create a browser-to-shell bypass.

## 4.15 Icons

- **Lucide Icons** for standard product icons;
- custom SynapseOS icons for domain concepts such as:
  - Agent;
  - Department;
  - Memory;
  - Decision;
  - Security veto;
  - Model router;
  - Context compression;
  - Tool call;
  - Review loop.

## 4.16 Command Palette

Use **Nuxt UI Command Palette** rather than introducing another heavy dependency initially.

Primary shortcut:

```text
Cmd/Ctrl + K
```

Candidate actions:

- open project;
- open agent;
- search tasks/runs;
- show failed runs;
- navigate to Security;
- pause/request pause where backend allows it;
- open audit;
- switch organization/workspace;
- switch docs language/version in the documentation app.

Candidate navigation shortcuts:

```text
G P → Projects
G A → Agents
G R → Runs
/   → Search
Esc → Close drawer/modal/palette
```

Shortcuts may become configurable later; they are not all mandatory for the first frontend slice.

---

# 5. Search, notifications, files, tables and task management

## 5.1 Global search

Initial decision:

```text
PostgreSQL + FastAPI search endpoint(s)
```

Do **not** introduce Meilisearch on day one.

A unified endpoint may look conceptually like:

```http
GET /search?q=oauth
```

Search targets can include:

- projects;
- agents;
- tasks;
- runs;
- decisions;
- audit events;
- skills;
- tools;
- documentation entries where applicable.

PostgreSQL full-text search and/or trigram search should be considered before adding another service.

### Meilisearch later

Meilisearch becomes justified when requirements include:

- hundreds of thousands or millions of highly searchable records;
- strong fuzzy matching;
- advanced ranking;
- instant autocomplete at scale;
- search latency that PostgreSQL can no longer meet acceptably.

If introduced later, search indexing must have explicit synchronization/consistency rules and failure handling.

## 5.2 Notifications

Validated model:

```text
SynapseOS backend
      ↓
Event stream / SSE
      ↓
Nuxt
├── immediate toast
└── persistent Notification Center
```

Examples:

- Reviewer requested changes;
- Security veto issued;
- Agent blocked;
- Provider unavailable;
- Task completed;
- Approval required;
- Budget threshold reached;
- Deployment finished/failed.

Severity model:

```text
INFO
→ task completed
→ agent assigned

WARNING
→ agent blocked
→ provider degraded
→ budget near threshold

CRITICAL
→ security veto
→ production deployment failed
→ sensitive permission escalation
→ provider outage affecting critical work
```

### Persistence rule

Persistent notifications are backend data. Read/unread state must not live only in Pinia.

### Deferred external channels

Later integrations may include:

- email;
- Slack;
- Discord;
- generic webhook.

They are not required for the first frontend implementation.

## 5.3 Files and artifacts

Validated storage architecture:

```text
PostgreSQL
→ metadata
→ ownership
→ project/task/run relationship
→ type
→ status
→ permissions
→ checksum

MinIO
→ actual object bytes
→ specifications
→ reports
→ screenshots
→ builds
→ artifacts
→ exports
```

Use **MinIO** as the initial self-hosted S3-compatible object storage.

Do not store large binaries directly in PostgreSQL unless a narrowly justified exception is documented.

Target upload flow:

```text
User / Agent
     ↓
FastAPI authorization + validation
     ↓
S3-compatible storage / MinIO
     ↓
PostgreSQL metadata
```

For large browser uploads, support **presigned URLs** so bytes can travel directly to object storage after the backend has authorized the operation.

Frontend capabilities:

- drag and drop;
- progress;
- cancel/retry where safe;
- preview where safe and supported;
- download;
- permission-aware actions;
- project/task/run association;
- checksum/status where relevant.

Never render untrusted HTML/file content directly in the application context without appropriate sandboxing/sanitization.

## 5.4 Large tables

Use **TanStack Table for Vue** for data-heavy screens.

Likely screens:

- Agents;
- Tasks;
- Runs;
- Audit logs;
- Decisions;
- Tool calls;
- Providers;
- Permissions;
- Artifacts.

Expected capabilities:

- multi-column sorting;
- server-side filtering;
- server-side pagination;
- row selection;
- hide/show columns;
- grouping where useful;
- persistent table preferences where useful;
- virtualization for large result sets;
- URL-serializable filters where navigation/bookmarking benefits.

Separation:

```text
Nuxt UI       → visual controls/primitives
TanStack Table → headless table behavior
```

Virtualization should be enabled only where necessary, not mechanically on every table.

## 5.5 Task management and Kanban

The task experience must include a true Trello/Jira-style **Kanban**, but the backend state machine remains authoritative.

Canonical task states currently include:

```text
BACKLOG
READY
ASSIGNED
IN_PROGRESS
WAITING_REVIEW
CHANGES_REQUESTED
WAITING_QA
WAITING_SECURITY
BLOCKED
COMPLETED
FAILED
CANCELLED
```

The UI may organize columns differently for usability, but it must never fabricate a transition the backend does not allow.

Example:

```text
IN_PROGRESS → WAITING_REVIEW
```

may be valid.

A direct browser move such as:

```text
BACKLOG → COMPLETED
```

must be rejected when the backend `TaskStateMachine` does not permit it.

### Drag and drop

Use **VueDraggable / SortableJS** for Kanban drag-and-drop instead of hand-rolling pointer interactions.

Drag/drop sequence:

1. user moves card;
2. UI computes requested transition;
3. backend command is sent;
4. backend validates permission + state transition;
5. successful response/event confirms state;
6. UI commits/reconciles visual state;
7. rejection restores previous state and explains the reason.

Optimistic updates must be used cautiously. For security-sensitive or workflow-critical transitions, confirmation from the backend may be preferable before final visual commitment.

### Task card fields

Possible card content:

- title;
- project;
- assigned agent;
- priority;
- status;
- progress where meaningfully defined;
- iteration count;
- reviewer;
- elapsed time;
- blocking reason;
- required approval/security state.

### Multiple task views

The same task model should support multiple representations:

```text
Kanban
→ day-to-day operational workflow

Table
→ dense analysis/filtering

Timeline
→ chronological history

Dependency Graph
→ dependency structure

Company View
→ who is working on what
```

The views must not each invent their own task state logic.

---

# 6. Internationalization

Use **`@nuxtjs/i18n` from V1**.

Initial locales:

```text
fr
en
```

Potential structure:

```text
i18n/
├── locales/
│   ├── en.json
│   └── fr.json
└── config.ts
```

No important user-facing business copy should be hardcoded repeatedly inside components.

Prefer:

```vue
<UButton>{{ $t('projects.actions.create') }}</UButton>
```

over:

```vue
<UButton>Créer un projet</UButton>
```

Domain key examples:

```text
agents.status.working
agents.status.blocked
tasks.status.waiting_review
security.veto
reviews.changes_requested
providers.unavailable
company.daily_briefing
```

### Canonical enum rule

Backend/database values remain canonical technical values, typically English uppercase enums:

```text
WAITING_REVIEW
CHANGES_REQUESTED
COMPLETED
```

The UI translates their labels:

```text
WAITING_REVIEW
→ En attente de revue
→ Waiting for review
```

Never localize stored enum values themselves.

Locale preference may be detected initially and persisted as a user preference once profile/settings contracts exist.

---

# 7. Design system

The design system is a product contract, not just a Tailwind configuration.

## 7.1 Direction

- dark-first;
- serious, technical and modern;
- compact information density;
- neutral background/surface palette;
- restrained accent color;
- semantic status colors;
- thin borders;
- minimal shadows;
- high readability;
- consistent status representation across every view.

## 7.2 Design tokens

Define tokens for at least:

```text
colors
spacing
radius
border
typography
elevation
motion
status
department
agent-state
```

Tokens should live in a reusable layer and be consumable by both `apps/web` and `apps/docs` once shared packages are introduced.

## 7.3 Typography

Use:

- a highly readable sans-serif for product UI;
- monospace for logs, IDs, commands, hashes, model names, token counts and technical metadata.

Exact font selection can be finalized during visual implementation, but it must preserve readability and license/deployment simplicity.

## 7.4 Agent statuses

At minimum support consistent representations for states such as:

```text
AVAILABLE
WORKING
BLOCKED
REVIEWING
FAILED
WAITING_APPROVAL
```

The same state must not appear green in one screen and orange in another without a defined semantic reason.

Color cannot be the only channel. Use icon, text, shape/badge, or another accessible cue.

## 7.5 Departments

Do not create a rainbow UI where every department receives a loud saturated color.

Use a neutral base and subtle visual signatures for departments such as:

- Engineering;
- Product;
- QA;
- Security;
- future departments.

## 7.6 Component principles

Important primitives include:

- sidebar;
- top bar;
- command palette;
- badge/status pill;
- drawer;
- modal;
- table controls;
- filter bar;
- empty state;
- error state;
- skeleton/loading state;
- timeline event;
- metric card;
- agent card;
- task card;
- confirmation/approval dialog;
- code/log block.

Build domain components on top of primitives. Avoid giant generic components controlled by dozens of boolean props.

---

# 8. Target Nuxt repository architecture

Use a **feature-first architecture**.

Do not put the entire application in a flat `components/` directory.

Target structure:

```text
apps/web/
├── app.vue
├── nuxt.config.ts
├── package.json
│
├── pages/
│   ├── index.vue
│   ├── company/
│   ├── projects/
│   ├── agents/
│   ├── tasks/
│   ├── runs/
│   ├── reviews/
│   ├── security/
│   ├── intelligence/
│   └── settings/
│
├── features/
│   ├── agents/
│   ├── projects/
│   ├── tasks/
│   ├── runs/
│   ├── reviews/
│   ├── permissions/
│   ├── security/
│   ├── providers/
│   ├── memory/
│   ├── context/
│   ├── notifications/
│   └── company-simulator/
│
├── components/
│   ├── ui/
│   ├── layout/
│   └── shared/
│
├── composables/
├── stores/
├── middleware/
├── layouts/
├── plugins/
├── utils/
├── types/
├── assets/
├── public/
│
├── api/
│   ├── generated/
│   └── adapters/
│
├── i18n/
│   └── locales/
│       ├── en.json
│       └── fr.json
│
└── tests/
```

Feature example:

```text
features/tasks/
├── components/
│   ├── TaskCard.vue
│   ├── TaskKanban.vue
│   └── TaskDetailsDrawer.vue
├── composables/
│   └── useTasks.ts
├── schemas/
│   └── task.schema.ts
├── types/
├── queries/
├── utils/
└── tests/
```

Responsibility rules:

```text
pages/
→ route-level composition

features/
→ domain-specific frontend behavior

components/ui/
→ reusable visual primitives

components/shared/
→ reusable cross-domain application components

api/generated/
→ Orval output only

api/adapters/
→ stable app-facing wrappers/mapping where needed

stores/
→ global client/UI state only

TanStack Query
→ remote/server state
```

## 8.1 Web app and documentation app

Long-term structure:

```text
apps/
├── web/
└── docs/

packages/
├── ui/
├── icons/
├── config/
└── optional shared tooling
```

Do not prematurely extract packages. Start with two apps and extract only genuinely shared code/design primitives.

---

# 9. Frontend security architecture

## 9.1 Zero-trust frontend principle

The browser is never a trusted policy enforcement boundary.

Frontend guards exist for UX/navigation. Backend authorization is mandatory for every sensitive operation.

```text
Authentication
→ Authentik / OIDC

Authorization
→ FastAPI + SynapseOS Permission Engine

Frontend route/button guards
→ UX only
```

## 9.2 Baseline protections

Implement and verify:

- strict Content Security Policy appropriate to the deployed app;
- XSS prevention and output encoding;
- explicit sanitization for any rich/untrusted rendered content;
- secure cookies where the selected auth/session architecture uses cookies;
- `HttpOnly` for session material that JavaScript does not need to access;
- `Secure` in HTTPS environments;
- appropriate `SameSite` policy;
- CSRF mitigation according to the final OIDC/session flow;
- minimal CORS allowlist on FastAPI;
- security headers;
- dependency auditing;
- no secret values in client bundles;
- no provider API keys in browser-accessible runtime configuration;
- no sensitive token persistence in `localStorage`.

If the chosen OIDC design supports a backend/BFF-style session with HttpOnly cookies, prefer it over persistent browser-readable bearer tokens.

## 9.3 Sensitive-data display policy

Do not display by default:

- API keys;
- access/refresh tokens;
- credentials;
- secret environment values;
- sensitive prompt portions;
- raw tool output that has not passed visibility/redaction rules;
- private file content outside user permissions.

## 9.4 Telemetry redaction

Before sending data to Sentry/OpenTelemetry/analytics/session replay:

- remove tokens;
- remove cookies/authorization headers;
- remove provider secrets;
- avoid raw prompts by default;
- avoid raw file content;
- avoid raw unrestricted tool responses;
- scrub query strings/URL params where secrets could appear;
- redact personal/sensitive workspace content according to policy.

Session replay, if enabled, must include masking/blocking rules for sensitive fields and surfaces.

## 9.5 xterm.js security

Required flow:

```text
xterm.js
   ↓
explicit frontend action
   ↓
FastAPI
   ↓
Permission Engine
   ↓
Command Runner / ToolExecutor
   ↓
bounded result
```

Forbidden architecture:

```text
xterm.js → direct host shell
```

Interactive terminal functionality, if introduced later, must still use backend command profiles, audit, timeout, workspace isolation and permission checks.

## 9.6 Risk-based confirmations

UI confirmation can reflect backend risk levels:

```text
LOW
→ immediate action if authorized

MEDIUM
→ explicit confirmation

HIGH
→ strong confirmation + clear consequences

CRITICAL
→ backend approval workflow required
```

Examples that may require elevated/critical treatment:

- delete workspace/project;
- production deployment;
- provider credential changes;
- permission elevation;
- security veto override;
- destructive tool execution.

A red modal is not a security boundary.

---

# 10. Responsive design and accessibility

## 10.1 Device strategy

SynapseOS is **desktop-first but responsive**, not conventionally mobile-first.

### Desktop

Full experience:

- Company Simulator;
- advanced Kanban;
- dense tables;
- complex graphs;
- terminal/log views;
- multi-panel Deep Inspect.

### Tablet

Full capability where practical, adapted through:

- collapsible panels;
- horizontal Kanban scrolling;
- simplified graph controls;
- drawer-based detail views.

### Mobile

Prioritize supervision and high-value actions:

- notifications;
- agents/statuses;
- tasks;
- approvals;
- incidents;
- lightweight run inspection.

Do not force the complete desktop Company Simulator onto a small screen. Use an alternate compact list/timeline representation of departments, agents, tasks and states.

## 10.2 Accessibility target

Target **WCAG 2.2 AA**.

Requirements:

- full keyboard operation for critical workflows;
- visible focus;
- logical focus order;
- accessible form labels;
- ARIA only where semantic HTML is insufficient;
- sufficient contrast;
- screen-reader-friendly statuses;
- error messages connected to inputs;
- no status communicated by color alone;
- accessible dialogs/drawers;
- accessible tables and sort controls;
- accessible command palette.

Core keyboard behavior:

```text
Cmd/Ctrl + K
Tab / Shift+Tab
Enter
Escape
Arrow keys
```

## 10.3 Reduced motion

Respect:

```css
prefers-reduced-motion
```

Company Simulator animations that are not essential must reduce or disable automatically. Semantic information must remain understandable without animation.

## 10.4 Accessibility testing

Use axe-core with Playwright for automated detection on critical routes, complemented by manual keyboard and screen-reader spot checks. Automated tooling is not considered complete accessibility validation by itself.

---

# 11. Build and deployment architecture

## 11.1 Container model

Validated target:

```text
Nuxt app
   ↓
Docker image
   ↓
reverse proxy
   ↓
HTTPS
```

Infrastructure choices:

- Docker;
- Docker Compose for development/self-hosted environments;
- GitHub Container Registry (GHCR);
- Traefik as preferred reverse proxy for the multi-service self-hosted topology;
- HTTPS/TLS termination;
- environment-specific runtime configuration;
- health checks.

## 11.2 Why Traefik

SynapseOS is expected to expose multiple independently deployable services. Traefik is a good fit for centralized routing/TLS in that topology.

Example hostnames:

```text
app.synapseos.dev
api.synapseos.dev
auth.synapseos.dev
docs.synapseos.dev
```

Potential service set:

```text
web
api
postgres
authentik
minio
ollama
observability
docs
```

This is not a requirement to start every service in every environment. Compose profiles or environment-specific stacks may be used to keep development lightweight.

## 11.3 Environments

At minimum:

```text
development
staging
production
```

Configurations and credentials must be isolated between environments.

Never make `staging` and `production` share mutable data stores or privileged secrets merely for convenience.

## 11.4 Nuxt runtime configuration

Use Nuxt runtime configuration deliberately:

```text
runtimeConfig
├── private
└── public
```

Only values explicitly safe for the browser belong in public runtime config.

Remember that anything sent to the client is public regardless of how the variable is named.

## 11.5 Health checks

Expose/check the minimum signals required to distinguish:

- process started;
- application ready;
- critical dependency unavailable where relevant.

Frontend health should not simply return healthy if the generated server cannot serve the app.

Backend readiness remains a separate concern.

---

# 12. CI/CD pipeline

CI/CD is a first-class SynapseOS subsystem, not an afterthought.

## 12.1 Workflow organization

Recommended structure:

```text
.github/workflows/
├── frontend-ci.yml
├── backend-ci.yml
├── e2e.yml
├── security.yml
├── docker.yml
├── deploy-staging.yml
└── deploy-production.yml
```

The exact split may be adjusted to avoid duplicated setup or excessive workflow overhead, but avoid one unreadable monolithic workflow.

## 12.2 Frontend pull-request quality gate

Target sequence:

```text
Pull Request
   ↓
install dependencies with locked versions
   ↓
ESLint
   ↓
TypeScript strict / Nuxt typecheck
   ↓
Vitest unit tests
   ↓
Vue Test Utils component tests
   ↓
Nuxt production build
   ↓
Playwright E2E where applicable
   ↓
Accessibility checks
   ↓
Dependency/security checks
```

A failed mandatory quality gate blocks merge according to repository protection rules.

## 12.3 Backend pipeline remains independent

The frontend must not replace the backend's quality pipeline. Existing backend checks continue independently, including the project's established tooling such as:

- Ruff;
- strict mypy;
- pytest;
- migration checks;
- security/invariant tests.

## 12.4 Cross-stack E2E pipeline

A dedicated integration pipeline should start the minimum real stack necessary for critical workflows, for example:

```text
Nuxt
FastAPI
PostgreSQL
Authentik
MinIO
required runtime dependencies
        ↓
Playwright
```

Critical scenario example:

```text
login
→ create/open project
→ create/open task
→ launch/observe authorized agent work
→ receive SSE update
→ reviewer workflow
→ changes requested
→ correction
→ completion
```

Do not make E2E tests depend on nondeterministic paid LLM behavior where a deterministic/fake provider contract can validate the frontend flow more reliably. Separate deterministic product-flow tests from optional live-provider smoke tests.

## 12.5 Docker image pipeline

After successful merge/release conditions:

```text
build image
→ scan image
→ push GHCR
→ assign immutable tag
```

Use immutable or traceable tags, for example:

```text
synapseos-web:sha-abc123
synapseos-web:1.4.0
synapseos-web:latest
```

`latest` must never be the only rollback reference.

## 12.6 Staging deployment

Typical target:

```text
main
 ↓
CI complete
 ↓
Docker image
 ↓
GHCR
 ↓
deploy staging
 ↓
health checks
 ↓
smoke tests
```

Staging deployment may be automatic after a protected successful main build.

## 12.7 Production deployment

Do not deploy production automatically merely because a commit hit `main`.

Preferred release model:

```text
release/tag
    ↓
known tested artifact
    ↓
production approval gate
    ↓
deploy
    ↓
health checks
    ↓
smoke tests
```

The approval gate may be manual initially. The key property is that production promotion is explicit and traceable.

## 12.8 Rollback

A failed deployment must have an operational rollback story:

```text
new deployment unhealthy
      ↓
select previous known-good immutable image
      ↓
rollback
      ↓
health + smoke verification
```

Rollback procedures must be documented and tested in staging before they are trusted in production.

## 12.9 Preview environments

Future enhancement:

```text
PR #142
→ preview-142.synapseos.dev
```

Useful for Company Simulator, Kanban and major UI changes.

Preview environments are deliberately deferred until CI, staging and deployment basics are stable.

## 12.10 CI/CD secrets

Secrets must come from protected GitHub Environments/Secrets or another approved secret-management mechanism.

Forbidden:

- committed `.env` secrets;
- hardcoded API keys in workflow YAML;
- passwords in Dockerfiles;
- secrets leaked via build args that become inspectable image metadata;
- echoing secrets in logs.

Use GitHub environments such as:

```text
development
staging
production
```

Production should have stronger protection/approval rules.

## 12.11 SynapseOS visualizes its own pipeline

Later, SynapseOS should ingest CI/CD events and render them as real organization activity.

Example:

```text
Developer Agent
    ↓
PR #142
    ↓
CI running

✓ Ruff
✓ mypy
✓ pytest
✓ frontend
● E2E
○ Security
○ Deploy
```

This is a real-data integration, not a fake simulator animation.

---

# 13. Official SynapseOS documentation site

SynapseOS must have a first-class public documentation product, not only raw Markdown rendered by GitHub.

## 13.1 Validated documentation stack

```text
apps/docs/
├── Nuxt
├── Nuxt Content
├── Nuxt UI
├── Tailwind CSS
├── @nuxtjs/i18n
└── Command Palette
```

Additional capabilities:

- Mermaid for architecture/workflow diagrams;
- OpenAPI-driven API reference;
- Scalar as the preferred modern OpenAPI renderer candidate;
- FR/EN;
- dark/light mode;
- documentation search;
- version-ready architecture;
- GitHub edit links;
- dedicated docs CI.

## 13.2 Product goal

Target experience quality is inspired by:

- Linear Docs;
- GitHub Docs;
- Vercel Docs;
- Stripe Docs;
- Supabase Docs.

The result should still have a distinct SynapseOS identity.

## 13.3 Target desktop layout

```text
┌─────────────────────────────────────────────────────────────┐
│ SynapseOS Docs        Search / Cmd+K             GitHub     │
├───────────────┬────────────────────────────┬────────────────┤
│ Navigation    │ Main documentation content │ On this page   │
│               │                            │                │
│ Getting Start │ Headings                   │ Overview       │
│ Concepts      │ Examples                   │ Configuration  │
│ Agents        │ Code blocks                │ Security       │
│ Tools         │ Diagrams                   │                │
│ Skills        │                            │                │
│ Memory        │                            │                │
│ API           │                            │                │
└───────────────┴────────────────────────────┴────────────────┘
```

## 13.4 Required UX

- compact left navigation;
- right-hand table of contents on capable screen sizes;
- global search;
- `Cmd/Ctrl + K`;
- dark/light mode;
- FR/EN;
- copy-code buttons;
- syntax highlighting;
- callouts;
- tabs;
- Mermaid diagrams;
- deep links to headings;
- previous/next navigation;
- responsive mobile navigation;
- edit-on-GitHub action;
- clear version indicator once versioning is active.

## 13.5 Documentation Command Palette

Example query:

```text
> agent runtime
```

Possible results:

```text
Agent Runtime
Create an Agent
Agent Lifecycle
Agent Permissions
Agent Runtime API
```

Actions can include:

- open GitHub repository;
- go to API reference;
- switch to French/English;
- switch documentation version;
- copy installation command;
- navigate to a concept/guide.

## 13.6 Documentation information architecture

Initial structure:

```text
01. Getting Started
    ├── Introduction
    ├── What is SynapseOS?
    ├── Installation
    ├── Quickstart
    └── Docker

02. Core Concepts
    ├── Agents
    ├── Departments
    ├── Projects
    ├── Tasks
    ├── Runs
    ├── Tools
    ├── Skills
    ├── Permissions
    ├── Reviews
    └── Loop Engineering

03. Architecture
    ├── System Overview
    ├── Agent Runtime
    ├── Tool Executor
    ├── Permission Engine
    ├── Multi-Agent Workflows
    ├── Memory
    ├── Context Intelligence
    ├── Model Router
    └── Audit System

04. Guides
    ├── Create an Agent
    ├── Create a Tool
    ├── Create a Skill
    ├── Add an LLM Provider
    ├── Build a Workflow
    └── Configure Permissions

05. API Reference
    ├── Authentication
    ├── Agents
    ├── Projects
    ├── Tasks
    ├── Runs
    └── Events

06. Deployment
    ├── Docker
    ├── Production
    ├── Authentik
    ├── MinIO
    └── Observability

07. Security

08. Contributing

09. Changelog
```

As the product evolves, CLI/SDK sections can be added when they actually exist.

## 13.7 Product docs vs engineering docs

Keep two audiences clear:

```text
Product documentation
→ how to use SynapseOS

Engineering documentation
→ how SynapseOS works internally
```

Example:

- “Create a project” is product documentation;
- “Developer ↔ Reviewer workflow internals” is engineering documentation.

Both belong in the official docs but should not be mixed into one overloaded page.

## 13.8 API reference

Do not maintain endpoint reference manually when FastAPI already emits OpenAPI.

Target chain:

```text
FastAPI
   ↓
openapi.json
   ↓
API documentation renderer
   ↓
SynapseOS API Reference
```

Scalar is the preferred candidate for a modern embedded API reference.

The API reference should inherit or visually align with the SynapseOS docs shell where practical.

## 13.9 Documentation search

Start simple:

- Nuxt Content-generated index/local search or another low-infrastructure approach compatible with the docs stack;
- Command Palette uses the same search data where practical.

Do not add Meilisearch before size/latency/fuzzy-search requirements justify it.

## 13.10 Documentation versioning

Architecture must be version-ready, e.g.:

```text
v1.0
v1.1
v2.0
```

A visible notice may eventually say:

```text
You are viewing SynapseOS v1.x
```

Do not create fake version complexity before the first stable public version exists.

## 13.11 Mermaid

Mermaid is strongly recommended for:

- multi-agent workflows;
- task state machines;
- LLM routing;
- Permission Engine flows;
- Context Intelligence Layer;
- deployment topology;
- CI/CD flows.

Diagrams must remain source-controlled and reviewable.

## 13.12 Documentation CI

Pull-request pipeline:

```text
Docs PR
 ↓
Markdown/MDC lint
 ↓
broken-link checks
 ↓
Nuxt typecheck
 ↓
production build
 ↓
preview/smoke validation
```

Broken internal links should fail CI once the link checker is stable enough to be authoritative.

Deployment:

```text
build docs
 ↓
Docker image / deploy artifact
 ↓
deploy
 ↓
docs.synapseos.dev
```

---

# 14. Observability UX and runtime-event model

The frontend should favor **structured events** over parsing human-readable logs.

## 14.1 Event envelope

The exact backend contract is backend-owned, but the frontend benefits from a normalized event shape conceptually containing:

```text
event_id
event_type
timestamp
workspace_id/project_id
task_id (optional)
run_id (optional)
agent_id (optional)
severity
summary
metadata (bounded/redacted)
correlation/trace id (where available)
```

## 14.2 Event ordering and reconnect

SSE implementation must define behavior for:

- reconnect;
- duplicate event delivery;
- missed event recovery where supported;
- out-of-order timestamps;
- disconnected/degraded banner;
- background-tab resume;
- query-cache reconciliation after reconnect.

The UI must not assume a TCP-like forever-perfect stream.

## 14.3 Timeline vs audit

Do not confuse:

- **operational timeline**: human-readable runtime progression;
- **audit log**: durable security/forensic record.

The frontend can display both, but a pretty timeline must not be treated as the authoritative audit trail.

---

# 15. Memory, RAG and Context Intelligence frontend readiness

The backend roadmap introduces memory progressively and includes a future Context Intelligence Layer. The frontend architecture must be ready to surface those capabilities without requiring them to exist on day one.

Potential future views:

- memory entries relevant to a task/agent;
- memory source and recency;
- retrieval hits/misses;
- memory hit rate;
- context budget usage;
- raw vs optimized context size;
- tokens saved by compression;
- context classification;
- provider/model route selected;
- reason/constraints for routing where safely exposable;
- access to raw source content only when permission and retention policies allow it.

D3 can support memory/context topology. ECharts can support aggregate compression/token metrics.

**Do not implement an elaborate RAG visualization before the backend memory contracts exist.**

---

# 16. Frontend implementation roadmap

> **Execution rule:** do not implement all phases at once. Each phase should normally map to a focused PR with its own tests, acceptance evidence, and explicit “not implemented” list.
>
> Package-install examples below use `pnpm` for readability. At implementation time, use the repository-standard package manager and commit the corresponding lockfile. Do not introduce a second package manager merely because an example uses `pnpm`.

## PHASE FE-0 — Backend readiness and contract inventory

### Objective

Confirm the backend is ready for the first frontend vertical slice and identify authoritative contracts before creating UI behavior.

### Work

- inventory existing FastAPI routes;
- export/inspect OpenAPI;
- inventory task states and transition endpoints;
- inventory auth/permission expectations;
- inventory agent/run/review/audit models;
- inventory SSE/event contracts if already implemented;
- identify endpoints that do **not** yet exist rather than mocking them as permanent assumptions;
- produce a frontend/backend contract matrix.

### Rules

- no backend business-rule duplication;
- no undocumented fake API contract committed as if final;
- no direct DB access from frontend;
- no “temporary” permission bypass.

### Tests/validation

- OpenAPI parses successfully;
- required first-slice endpoints are listed with status: available / missing / unstable;
- all backend enums used by the first slice are mapped without renaming their canonical values.

### Acceptance criteria

- frontend team can name the backend source of truth for auth, task state, permissions and run events;
- known contract gaps are explicit.

### Deliberately out of scope

- visual implementation;
- Company Simulator;
- speculative endpoints.

### Definition of Done

Contract inventory reviewed before FE-1 begins.

---

## PHASE FE-1 — Nuxt + TypeScript application bootstrap

### Objective

Create `apps/web` as a minimal, strict, production-buildable Nuxt application.

### Install

Conceptually:

```bash
pnpm add nuxt vue
pnpm add -D typescript eslint
```

Use Nuxt-recommended setup/version commands at implementation time instead of copying stale versions from this document.

### Configuration

- strict TypeScript;
- environment/runtime config skeleton;
- ESLint;
- formatting convention;
- build scripts;
- basic test scripts;
- no secrets in checked-in config.

### Target files

```text
apps/web/
├── app.vue
├── nuxt.config.ts
├── package.json
├── tsconfig.json
├── pages/
├── components/
├── features/
├── composables/
├── stores/
├── api/
├── i18n/
└── tests/
```

### Rules

- no business features yet;
- no direct fetch wrappers spread across components;
- no disabling TypeScript strictness to make bootstrap pass.

### Tests

- app mounts;
- production build succeeds;
- typecheck succeeds;
- lint succeeds.

### Common errors

- client/server API usage mixed accidentally;
- runtime environment secrets placed in public config;
- duplicate app initialization plugins.

### Acceptance criteria

A clean Nuxt shell builds in CI-equivalent conditions.

### Deliberately out of scope

Auth, API generation, simulator and feature pages.

---

## PHASE FE-2 — Nuxt UI + Tailwind + design tokens

### Objective

Establish the visual foundation without building domain features.

### Install

Install current Nuxt UI/Tailwind integration according to official Nuxt UI guidance.

### Configuration

Define:

- dark-first theme;
- light-mode compatibility;
- neutral surface scale;
- primary accent;
- semantic statuses;
- spacing/radius/border/elevation tokens;
- typography and monospace roles;
- motion tokens;
- focus styles.

### Target files

Possible structure:

```text
apps/web/assets/css/main.css
apps/web/app.config.ts
apps/web/components/ui/
apps/web/components/layout/
```

Shared tokens may move to `packages/ui` later.

### Rules

- avoid one-off hex values throughout feature components;
- color is never the only status cue;
- no excessive shadows/gradients that contradict the validated identity;
- reusable primitives before duplicated markup.

### Tests

- representative primitives render in dark/light modes;
- focus is visible;
- semantic status components have textual/icon cues;
- basic visual regression may be added once stable.

### Common errors

- over-customizing Nuxt UI before real screens exist;
- department rainbow palette;
- contrast regressions in dark mode.

### Acceptance criteria

A small internal showcase page demonstrates the agreed SynapseOS visual language.

### Deliberately out of scope

Company Simulator choreography and custom D3 graphics.

---

## PHASE FE-3 — Application shell, navigation and Command Palette

### Objective

Create the stable navigation skeleton for Company View, Control Center and Deep Inspect entry points.

### Technology

- Nuxt layouts/pages;
- Nuxt UI navigation primitives;
- Nuxt UI Command Palette;
- Lucide Icons.

### Install

Install Lucide Vue integration if not already pulled transitively/available through the chosen Nuxt UI setup.

### Configuration/integration

- compact sidebar;
- responsive header;
- workspace/project context location;
- `Cmd/Ctrl+K` global palette;
- route search/action registry;
- keyboard focus management.

### Target files

```text
layouts/default.vue
components/layout/AppSidebar.vue
components/layout/AppHeader.vue
features/command-palette/
pages/company/
pages/projects/
pages/agents/
pages/tasks/
pages/runs/
pages/security/
pages/intelligence/
```

### Rules

- palette actions invoking mutations still go through normal permission-aware API flows;
- keyboard shortcuts must not conflict with text inputs;
- no inaccessible div-only navigation.

### Tests

- keyboard opens/closes palette;
- arrow/enter navigation works;
- routes are reachable;
- mobile sidebar works;
- `Esc` restores focus appropriately.

### Common errors

- global shortcut firing while typing;
- focus trapped after drawer close;
- route and palette registries drifting apart.

### Acceptance criteria

All primary sections can be reached by navigation and keyboard without feature implementations.

---

## PHASE FE-4 — i18n foundation

### Objective

Make FR/EN a structural capability before feature text proliferates.

### Technology

`@nuxtjs/i18n`.

### Install

```bash
pnpm add @nuxtjs/i18n
```

Verify the current official module setup for the selected Nuxt version.

### Configuration

- `fr` and `en` locales;
- explicit fallback locale;
- consistent key naming;
- locale-switch UI;
- persistence strategy when user settings exist.

### Files

```text
i18n/locales/fr.json
i18n/locales/en.json
i18n/config.ts
```

### Rules

- never translate backend enum values themselves;
- translate labels/messages around canonical values;
- no feature ships with large new blocks of hardcoded user-facing strings.

### Tests

- locale switching;
- missing-key behavior;
- enum-label mapping;
- critical pages render in both locales.

### Common errors

- using translated strings as API values;
- concatenating translated fragments that break grammar;
- duplicate keys with different meaning.

### Acceptance criteria

Shell and design-system showcase are fully usable in FR and EN.

---

## PHASE FE-5 — Orval API generation and adapters

### Objective

Make FastAPI OpenAPI the source of frontend API types and reduce hand-maintained contract drift.

### Technology

Orval + generated TypeScript client/TanStack Query bindings.

### Install

Install Orval as a development dependency and the HTTP/query integration selected by its current Nuxt/Vue guidance.

### Configuration

- OpenAPI source path/URL;
- deterministic generated output;
- generated folder excluded from manual edits;
- generation script;
- CI check that generation is up to date where practical.

### Files

```text
orval.config.*
api/generated/
api/adapters/
```

### Integration rules

- UI components do not import low-level generated internals everywhere;
- use feature composables/adapters for behavior that needs mapping, caching policy or permission-aware UX;
- avoid rewriting backend-generated DTOs by hand unless a UI-specific view model is genuinely different.

### Tests

- generation succeeds against current OpenAPI;
- generated client typechecks;
- a smoke request to `/health` or safe endpoint succeeds in integration environment.

### Common errors

- committing stale generated files;
- manual changes overwritten by regeneration;
- generated nullable/optional semantics ignored by UI.

### Acceptance criteria

A documented single command regenerates the API layer reproducibly.

---

## PHASE FE-6 — TanStack Query server-state layer

### Objective

Establish one coherent strategy for remote data caching, loading, retries and invalidation.

### Install

Install the current `@tanstack/vue-query` package.

### Configuration

Define defaults for:

- stale times by data class;
- retry policy;
- refetch behavior;
- mutation invalidation;
- error normalization;
- offline/reconnect behavior where useful.

### Rules

- server state belongs here, not copied wholesale into Pinia;
- do not retry unsafe mutations blindly;
- authentication failures are not normal retriable network errors;
- permission failures should surface clearly.

### Tests

- query loading/success/error;
- invalidation after mutation;
- retry boundaries;
- cache update after SSE reconciliation later.

### Common errors

- default retries hammering failed providers/endpoints;
- stale cached permission view after role change;
- query keys inconsistent across features.

### Acceptance criteria

At least one real backend resource uses the standard query abstraction end-to-end.

---

## PHASE FE-7 — Pinia client/UI state

### Objective

Introduce Pinia only for genuine application/client state.

### Install

Install Pinia/Nuxt integration according to current Nuxt guidance.

### Suggested stores

- UI preferences;
- simulator viewport/presentation state;
- selected contextual entity where route state is insufficient;
- non-server command-palette preferences;
- ephemeral global UI state.

### Rules

Do not create stores that mirror `projects`, `tasks`, `runs`, etc. when TanStack Query already owns them.

### Tests

- store actions/getters;
- persistence only for explicitly safe preferences;
- reset on logout/workspace change where required.

### Common errors

- persisted sensitive state;
- server cache duplication;
- cross-workspace stale selections.

### Acceptance criteria

Pinia has a small, clearly documented responsibility boundary.

---

## PHASE FE-8 — Authentik OIDC integration

### Objective

Use a mature identity provider instead of building password/session identity from scratch.

### Technology

Authentik + OIDC.

### Infrastructure installation

Authentik runs in the Docker/self-hosted infrastructure, using the current official Authentik deployment requirements.

### Configuration

- OIDC application/provider for SynapseOS;
- redirect/callback URIs for development/staging/production;
- logout flow;
- groups/claims only where useful;
- MFA policy as deployment policy requires;
- secret storage outside client bundle.

### Nuxt integration

Prefer a secure session architecture in which browser-readable long-lived tokens are minimized. Exact implementation can use an appropriate Nuxt server/BFF/session mechanism if compatible with the final deployment design.

### FastAPI integration

FastAPI validates identity/token/session context and maps authenticated identity to SynapseOS authorization context. Business roles remain SynapseOS-owned.

### Rules

- no custom password storage in Nuxt;
- no provider secrets in client runtime config;
- no auth token persisted in `localStorage` by default;
- route middleware is UX, not authorization;
- logout clears local caches and sensitive UI state.

### Tests

- login redirect/callback;
- authenticated API request;
- expired session;
- logout;
- unauthorized/forbidden behavior;
- workspace switching does not leak prior cached data.

### Common errors

- callback URL mismatch;
- CORS/CSRF confusion;
- ID token used incorrectly as API authorization token;
- browser-readable refresh tokens persisted insecurely;
- frontend role claim treated as final authority.

### Acceptance criteria

A user can authenticate through Authentik and FastAPI independently enforces authorization.

### Deliberately out of scope

Building a custom identity provider.

---

## PHASE FE-9 — Forms: Zod + vee-validate

### Objective

Standardize form parsing, validation and error UX.

### Install

```bash
pnpm add zod vee-validate
```

Add the current supported Zod integration adapter if the selected versions require it.

### Rules

- Zod is client validation, not backend authority;
- backend validation errors must map cleanly to forms;
- sensitive fields never logged;
- reusable domain schemas live with their features.

### Tests

- valid/invalid submission;
- backend validation mapping;
- touched/dirty state;
- keyboard submission;
- error-summary/focus behavior on complex forms.

### Common errors

- duplicating Pydantic semantics imperfectly;
- treating frontend validation as security;
- losing server error detail.

### Acceptance criteria

First project/task/settings forms share a consistent validation pattern.

---

## PHASE FE-10 — SSE real-time event stream

### Objective

Add one robust server→browser live event channel for runtime updates before introducing WebSockets.

### Technology

Server-Sent Events (SSE), using the browser/EventSource-compatible approach or a small client wrapper when headers/auth requirements demand it.

### Backend prerequisite

A stable, permission-filtered SSE endpoint with documented event types and reconnect semantics.

### Integration

Create a dedicated real-time layer instead of opening EventSource connections ad hoc inside pages.

Potential structure:

```text
features/realtime/
├── composables/useEventStream.ts
├── event-types.ts
├── event-router.ts
├── reconnect-policy.ts
└── tests/
```

### Event handling

Events should update:

- visible timelines;
- notification triggers;
- TanStack Query cache/invalidation;
- Company Simulator state;
- run/status badges.

### Required behavior

- reconnect with bounded backoff;
- detect disconnected/degraded state;
- deduplicate events when event IDs exist;
- reconcile critical server state after reconnect;
- cleanly close streams on logout/context change;
- prevent cross-workspace event leakage;
- avoid unbounded in-memory event history.

### Tests

- connection established;
- event routing;
- duplicate event handling;
- reconnect;
- logout closes stream;
- workspace switch closes/reopens scoped stream;
- malformed/unknown event handled safely;
- cache reflects authoritative state after reconnect.

### Common errors

- creating one stream per component;
- treating SSE as guaranteed exactly-once delivery;
- memory leak from listeners;
- stale state after network sleep/resume;
- exposing events the user is no longer allowed to observe.

### Acceptance criteria

An agent/task/run status can change in the backend and appear in the UI without polling as the normal path.

### Deliberately out of scope

WebSocket interactive terminal/chat.

---

## PHASE FE-11 — Notifications and toast system

### Objective

Turn relevant backend events into useful, persistent and non-spammy user notifications.

### Technology

- Nuxt UI toast primitives;
- backend-persisted Notification Center;
- SSE for live delivery.

### UI

Implement:

- toast for immediate feedback;
- notification drawer/center;
- unread count;
- severity;
- mark read/unread;
- link to relevant project/task/run/review;
- empty/error/loading states.

### Rules

- not every SSE event deserves a toast;
- notification persistence comes from backend;
- user must be able to distinguish informational, warning and critical items;
- do not expose sensitive payload details in notification previews.

### Tests

- real-time notification arrival;
- unread persistence;
- mark read;
- duplicate suppression where backend/event IDs permit;
- critical notification accessibility;
- deep link destination.

### Acceptance criteria

Reviewer changes, security veto, agent block and approval-required scenarios are surfaced appropriately.

### Deliberately out of scope

Email/Slack/Discord/webhook channels.

---

## PHASE FE-12 — Data-heavy tables with TanStack Table

### Objective

Create reusable table architecture for dense operational data.

### Install

Install the current Vue package for TanStack Table and virtualization package only if a measured use case requires it.

### First candidate

Runs or Agents table.

### Capabilities

- server pagination;
- server sorting;
- server filters;
- column visibility;
- row actions;
- loading skeleton;
- empty state;
- error state;
- accessible headers/sorting;
- optional row selection.

### URL state

For valuable shareable views, serialize stable filters/sort/page into the URL.

### Tests

- sort mapping to API;
- filters;
- pagination;
- invalid URL filter fallback;
- loading/error/empty;
- keyboard-accessible row actions.

### Common errors

- loading full datasets into browser just to sort;
- unstable column IDs;
- virtualization breaking keyboard navigation;
- table state diverging from URL/query cache.

### Acceptance criteria

One production-grade table becomes the reference implementation for later data screens.

---

## PHASE FE-13 — Project and task operational UI

### Objective

Create the first substantial Control Center vertical slice using real backend projects/tasks.

### Features

- project list/detail;
- task list/detail;
- task filters;
- task state visualization;
- permissions-aware actions;
- task history/timeline link;
- dependency summaries.

### Rules

- canonical backend states displayed, not redefined;
- transitions always requested from backend;
- mutation errors retain previous authoritative state;
- acceptance criteria and blocking reason remain visible where useful.

### Tests

- create/view/update supported project/task fields;
- forbidden mutations;
- invalid transition feedback;
- status updates arriving through SSE;
- i18n labels for all known states.

### Acceptance criteria

A user can manage/inspect tasks without needing the future simulator.

---

## PHASE FE-14 — Kanban + drag and drop

### Objective

Add the validated Trello/Jira-style task board on top of the already working task APIs.

### Technology

VueDraggable / SortableJS.

### Install

Install the maintained Vue wrapper/SortableJS package selected at implementation time; verify Nuxt SSR/client compatibility.

### Behavior

- columns map to canonical workflow states or documented groups;
- drag requests a backend state transition;
- backend validates state + actor permission;
- rejection restores the card and explains why;
- real-time events reconcile moves initiated by agents/other users.

### Accessibility

Drag/drop must have an accessible alternative. A user unable to use pointer drag must still be able to request an allowed transition through keyboard/menu actions.

### Tests

- valid drag;
- invalid drag;
- permission denied;
- concurrent external status change;
- SSE reconciliation;
- keyboard alternative;
- mobile horizontal board behavior.

### Common errors

- optimistic card move never rolled back;
- duplicated task after concurrent event;
- direct client-only reorder mistaken for backend transition;
- inaccessible drag-only interaction.

### Acceptance criteria

Kanban is a representation of the real `TaskStateMachine`, not a separate workflow engine.

---

## PHASE FE-15 — Runs, reviews, approvals and Deep Inspect timeline

### Objective

Expose the core engineering loop in a readable operational view.

### Features

- run list/detail;
- iteration timeline;
- developer evidence summary;
- reviewer request/result;
- changes-requested path;
- approvals;
- tool call summaries;
- security-related stops where available;
- correlation/trace navigation when safe.

### UX separation

Use:

- human-readable structured timeline first;
- raw/technical evidence behind expandable Deep Inspect surfaces.

### Rules

- never expose provider secrets or raw sensitive prompts by default;
- reviewer “approved” label maps to backend result;
- frontend cannot manufacture approval;
- audit identifiers remain linkable where permissions permit.

### Tests

- completed/failed/cancelled run;
- multi-iteration run;
- reviewer changes request;
- approval required/denied;
- missing redacted fields handled gracefully.

### Acceptance criteria

A user can understand why an agent workflow succeeded, failed, or stopped without reading raw logs first.

---

## PHASE FE-16 — xterm.js raw logs / technical console

### Objective

Provide a terminal-quality presentation for bounded command/log output without bypassing SynapseOS execution controls.

### Install

Install `xterm`/current xterm.js packages and required fit/resize add-ons only as needed.

### Configuration

- read-only by default;
- resize handling;
- bounded buffer/history;
- safe copy behavior;
- clear stdout/stderr distinction if backend provides it;
- sanitized URLs/escape sequences where applicable.

### Security rules

- no direct SSH/host shell;
- no browser-supplied arbitrary command execution unless a future backend capability explicitly authorizes it;
- command actions pass Permission Engine/Command Runner;
- output visibility follows workspace/project permissions;
- dangerous terminal escape/content handling reviewed.

### Tests

- large bounded output;
- resize;
- redacted content;
- permission denied;
- terminated/cancelled command;
- no uncontrolled memory growth.

### Common errors

- treating xterm as a shell backend;
- rendering infinite logs;
- ANSI/escape handling security bugs;
- secrets copied into telemetry.

### Acceptance criteria

Technical logs are inspectable without weakening backend command isolation.

---

## PHASE FE-17 — Analytics with ECharts

### Objective

Add standard operational analytics only after reliable metrics endpoints exist.

### Install

Install ECharts and a Vue/Nuxt-friendly integration pattern compatible with client-side rendering.

### Initial charts

- tokens by project/time;
- run success/failure;
- latency by provider/model;
- retries/iterations;
- tool-call volume;
- cost where cost data is available;
- security findings;
- agent reliability/reputation trends where meaningful.

### Rules

- charts must include accessible labels/summary values;
- avoid misleading axes/truncated scales;
- distinguish missing data from zero;
- confidence/reputation metrics require explanatory copy/tooltip.

### Tests

- data transform unit tests;
- empty/partial data;
- timezone boundaries;
- responsive rendering;
- locale number/date formatting.

### Acceptance criteria

Charts summarize real metrics and link to underlying records where useful.

---

## PHASE FE-18 — Company Simulator V1 with Vue Flow

### Objective

Create the first immersive company representation using real agents, departments, tasks and events.

### Install

Install the current Vue Flow packages and required style assets.

### Node types

Potential custom nodes:

- Department;
- Agent;
- Task/work item;
- Review gate;
- Security gate;
- workflow boundary.

### Behavior

- pan/zoom/select;
- semantic agent status;
- task/assignment edges;
- click opens detail drawer;
- live SSE state updates;
- no fake “busy” animation when backend is idle.

### State shown on agent selection

Where available and authorized:

- role;
- status;
- task;
- model;
- tokens/cost;
- runtime;
- iteration;
- tools;
- last action;
- confidence.

### Tests

- node rendering from real DTOs;
- status change via SSE;
- selection/deep link;
- empty company;
- large department fallback/performance;
- reduced-motion behavior.

### Common errors

- overloading graph with every event;
- animations disconnected from backend truth;
- inaccessible node interaction;
- storing business state only inside graph node state.

### Acceptance criteria

A user can inspect “who is doing what” through the graph and reach the same authoritative records as Control Center.

---

## PHASE FE-19 — Motion for Vue and semantic simulator animation

### Objective

Add motion after Company Simulator state correctness is established.

### Technology

Motion for Vue as primary motion layer.

### Uses

- agent status transitions;
- card/panel entrance/exit;
- drawer transitions;
- work-state feedback;
- layout transitions.

### Rules

- motion communicates state change;
- reduced-motion is honored;
- no infinite decorative animation consuming resources;
- animation cannot delay critical security/status information.

### Tests

- state visible with animations disabled;
- reduced-motion behavior;
- no layout interaction blocked during transition.

### Acceptance criteria

Animations improve comprehension without becoming the product logic.

---

## PHASE FE-20 — GSAP advanced choreography

### Objective

Add only the simulator sequences that require coordinated timelines beyond normal UI motion.

### Technology

GSAP.

### Candidate uses

- developer → reviewer dossier handoff;
- multi-agent task packet movement;
- synchronized department sequence;
- complex workflow replay.

### Rules

- introduce GSAP only when a concrete sequence cannot be expressed cleanly with existing primitives;
- lifecycle cleanup is mandatory;
- reduced-motion fallback is mandatory;
- no business timing depends on animation timing.

### Tests

- lifecycle cleanup;
- route leave/unmount;
- reduced-motion fallback;
- event interruption/cancellation.

### Acceptance criteria

GSAP remains a specialized layer, not a dependency of ordinary buttons/cards.

---

## PHASE FE-21 — D3 advanced visualization layer

### Objective

Implement custom analytical/relationship visualizations after the underlying data contracts exist.

### Install

Install only the D3 modules actually needed where practical rather than importing an oversized surface without reason.

### Candidate visualizations

- agent heatmap;
- inter-department flow;
- complex dependency topology;
- decision network;
- memory/RAG topology;
- Context Intelligence flow.

### Rules

- do not recreate Vue Flow;
- accessible textual/table fallback for critical information;
- isolate D3 DOM lifecycle from Vue lifecycle carefully;
- bounded data volumes and aggregation for large graphs.

### Tests

- deterministic data transforms;
- mount/update/unmount;
- resize;
- empty/large datasets;
- no event-listener leak.

### Acceptance criteria

Each D3 visualization answers a question that standard ECharts/Vue Flow could not answer sufficiently.

---

## PHASE FE-22 — MinIO file/artifact experience

### Objective

Add secure file/artifact browsing and upload once backend object-storage contracts are available.

### Infrastructure

MinIO runs as S3-compatible object storage. Browser does not receive unrestricted storage credentials.

### Backend integration

FastAPI owns:

- authorization;
- metadata;
- presigned URL issuance;
- object relation to project/task/run;
- type/size/checksum policy;
- deletion policy;
- audit where needed.

### Frontend

- upload manager;
- drag/drop;
- progress;
- retry/cancel semantics;
- artifact list;
- safe preview;
- download;
- link to provenance (task/run).

### Tests

- authorized upload;
- forbidden upload;
- size/type rejection;
- expired presigned URL;
- network interruption;
- object exists but metadata missing / metadata exists but object unavailable;
- safe filename display.

### Common errors

- S3 root credentials in browser;
- trusting MIME type supplied by browser;
- direct rendering of active HTML/SVG without sandbox policy;
- orphan objects without cleanup strategy.

### Acceptance criteria

Artifacts are traceable, permission-aware and do not route all large bytes through FastAPI unless intentionally chosen.

---

## PHASE FE-23 — Global search

### Objective

Add unified navigation/search across core SynapseOS records.

### Initial backend

FastAPI + PostgreSQL search.

### Frontend integration

- Command Palette integration;
- dedicated search results page if necessary;
- entity grouping;
- keyboard navigation;
- permission-scoped results;
- highlighted match snippets only when safe.

### Tests

- project/agent/task/run search;
- no unauthorized record leakage;
- fuzzy/partial behavior exactly matches documented backend capability;
- empty/no-results states;
- keyboard selection.

### Acceptance criteria

A user can reach important records without manually navigating hierarchy.

### Deliberately out of scope

Meilisearch until justified by measured requirements.

---

## PHASE FE-24 — Sentry frontend observability

### Objective

Capture actionable frontend failures without leaking sensitive SynapseOS data.

### Install/configuration

Install current official Sentry Nuxt integration and configure per environment.

### Capture

- unhandled frontend errors;
- stack traces/source maps according to secure deployment policy;
- key performance spans;
- failed network requests with sanitized metadata;
- optional session replay only after privacy masking is configured.

### Redaction rules

Never intentionally send:

- authorization headers;
- API keys;
- raw prompts;
- unrestricted tool outputs;
- raw private file contents;
- secret form values.

### Tests

- test event arrives in non-production environment;
- redaction unit tests;
- environment tagging;
- source map behavior;
- replay masking if enabled.

### Acceptance criteria

A frontend exception can be diagnosed from Sentry without exposing secret runtime content.

---

## PHASE FE-25 — OpenTelemetry distributed correlation

### Objective

Correlate frontend requests with backend/runtime traces while preserving privacy.

### Integration

Propagate approved trace context across:

```text
Nuxt → FastAPI → Orchestrator → Agent → Tool → LLM → Reviewer
```

### Rules

- do not place prompts/file content in span attributes;
- bounded attribute cardinality;
- no secrets;
- sampling policy appropriate to environment;
- frontend trace IDs can link Deep Inspect to backend trace views only when authorized.

### Tests

- trace propagation;
- correlation ID visible where expected;
- sensitive-field redaction;
- failed request captured with safe metadata.

### Acceptance criteria

A cross-stack request can be followed end-to-end without turning tracing into a data-exfiltration path.

---

## PHASE FE-26 — Responsive and accessibility hardening

### Objective

Move accessibility/responsiveness from local component checks to full-product validation.

### Work

- desktop/tablet/mobile audit;
- mobile supervision views;
- Company Simulator alternate mobile view;
- keyboard-only walkthrough;
- focus audit;
- contrast audit;
- `prefers-reduced-motion` audit;
- Playwright + axe critical-route coverage.

### Acceptance criteria

Critical workflows are keyboard-operable, understandable without color/motion, and usable at supported viewport classes.

---

## PHASE FE-27 — CI pipeline for frontend

### Objective

Make frontend quality gates reproducible and branch-protection ready.

### Workflow

Implement `frontend-ci.yml` or equivalent with:

- locked install;
- lint;
- strict typecheck;
- unit tests;
- component tests;
- build;
- selected E2E/accessibility checks;
- dependency checks.

### Rules

- fail fast on deterministic quality errors;
- cache dependencies safely;
- do not hide failures with `continue-on-error` on mandatory gates;
- CI scripts match local scripts.

### Tests

The workflow itself is validated by a PR with intentional failures corrected before merge.

### Acceptance criteria

A clean checkout can reproduce all mandatory checks.

---

## PHASE FE-28 — Cross-stack E2E and security pipeline

### Objective

Validate real system integration beyond isolated frontend tests.

### Work

- launch test stack;
- deterministic/fake LLM provider where appropriate;
- Authentik test identity flow;
- PostgreSQL migrations;
- MinIO when file flows are in scope;
- Playwright critical workflows;
- security/dependency/image scanning.

### Acceptance criteria

The primary project→task→agent/run→review flow is validated against real HTTP/auth/event boundaries.

---

## PHASE FE-29 — Docker, GHCR and staging deployment

### Objective

Produce immutable deployable frontend artifacts and deploy staging automatically after approved main changes.

### Work

- production Dockerfile;
- `.dockerignore`;
- image health strategy;
- GHCR push;
- SHA/version tags;
- Traefik labels/config;
- staging environment variables;
- staging smoke tests.

### Acceptance criteria

A merged known-good build produces a traceable image and healthy staging deployment.

---

## PHASE FE-30 — Protected production release + rollback

### Objective

Create explicit, auditable production promotion.

### Work

- protected GitHub environment;
- approval gate;
- release/tag policy;
- immutable artifact promotion;
- health/smoke tests;
- documented rollback to known-good image.

### Acceptance criteria

A staging-tested release can be promoted and deliberately rolled back without rebuilding a different artifact.

---

## PHASE FE-31 — Official docs app bootstrap

### Objective

Create `apps/docs` as a polished independent Nuxt documentation app.

### Technology

- Nuxt;
- Nuxt Content;
- Nuxt UI;
- Tailwind;
- i18n.

### Install

Use current official Nuxt Content and Nuxt UI setup for the chosen Nuxt version.

### Structure

```text
apps/docs/
├── content/
├── components/
├── layouts/
├── pages/
├── public/
├── i18n/
└── nuxt.config.ts
```

### Acceptance criteria

Docs app renders local Markdown/MDC with the SynapseOS design language and builds independently from `apps/web`.

---

## PHASE FE-32 — Docs navigation, search and Command Palette

### Objective

Deliver the modern Linear/GitHub/Vercel-style docs navigation experience.

### Features

- left nav;
- table of contents;
- full-text/local content search;
- `Cmd/Ctrl+K`;
- keyboard navigation;
- deep links;
- previous/next;
- mobile nav;
- edit-on-GitHub links.

### Rules

- one search index/source of truth where practical;
- no Meilisearch until justified;
- search results respect currently selected docs version/language once those concepts exist.

### Tests

- search;
- keyboard palette;
- broken routes;
- mobile nav;
- heading deep links.

### Acceptance criteria

A user can navigate the docs primarily through sidebar, search or keyboard.

---

## PHASE FE-33 — Mermaid + rich documentation components

### Objective

Support architecture-grade technical documentation without screenshots for every concept.

### Features

- Mermaid;
- code blocks;
- copy button;
- tabs;
- callouts;
- warnings;
- step components where useful.

### Rules

- Mermaid source remains reviewable text;
- diagrams have surrounding explanatory text;
- code samples are tested/linted where feasible;
- avoid decorative diagrams with no technical purpose.

### Acceptance criteria

Existing architecture/state-machine docs can migrate/render clearly in the official site.

---

## PHASE FE-34 — OpenAPI / Scalar API reference

### Objective

Generate a modern API reference from FastAPI instead of duplicating endpoint documentation manually.

### Integration

```text
FastAPI openapi.json
       ↓
Scalar (or validated equivalent)
       ↓
SynapseOS docs shell / API Reference
```

### Rules

- OpenAPI remains authoritative;
- docs build should detect invalid/unavailable schema in CI where practical;
- examples must not contain real secrets;
- auth instructions clearly distinguish identity from business permission.

### Acceptance criteria

API reference updates when backend OpenAPI changes, with minimal manual duplication.

---

## PHASE FE-35 — Documentation i18n and version readiness

### Objective

Support FR/EN and prepare, without overbuilding, for real release versioning.

### Work

- locale navigation;
- localized core content;
- fallback rules;
- version selector architecture behind a feature that only activates once versions exist;
- visible current version once stable releases exist.

### Rules

- do not fabricate version history;
- clearly indicate untranslated/fallback content if needed;
- versioned docs must remain linkable/bookmarkable.

### Acceptance criteria

Core docs are usable in FR/EN and the architecture can add v1/v2 without redesigning navigation.

---

## PHASE FE-36 — Documentation CI/CD

### Objective

Treat docs as production software.

### Pipeline

- Markdown/MDC lint;
- links;
- Nuxt typecheck;
- build;
- search/index generation validation;
- preview/smoke;
- deploy `docs.synapseos.dev`.

### Acceptance criteria

Broken internal links/build failures block docs deployment.

---

## PHASE FE-37 — Future WebSocket interactive capabilities

### Objective

Introduce WebSocket only after a real bidirectional requirement exists.

### Possible scope

- interactive terminal;
- direct agent conversation/control;
- collaborative sessions.

### Required safeguards

- authentication and authorization on connection + commands;
- workspace scoping;
- heartbeat/reconnect;
- backpressure/bounded buffers;
- audit;
- Command Runner/ToolExecutor remains authoritative;
- no raw shell bypass.

### Deliberately deferred

This phase must not be pulled forward just because WebSockets appear “more real-time” than SSE.

---

## PHASE FE-38 — Future Meilisearch migration if justified

### Objective

Improve global search only after PostgreSQL search is demonstrably insufficient.

### Entry criteria

At least one measured need such as:

- unacceptable latency;
- strong fuzzy ranking requirements;
- large indexed corpus;
- autocomplete requirements beyond PostgreSQL solution.

### Work

- index ownership;
- async synchronization;
- reindex strategy;
- deletion/permission propagation;
- failure/degraded mode;
- observability.

### Security rule

A search index must never become a side channel exposing records the API would forbid.

---

## PHASE FE-39 — Future preview environments per PR

### Objective

Provide disposable UI review environments after core CI/deployment is stable.

### Example

```text
PR #142 → preview-142.synapseos.dev
```

### Requirements

- isolated config;
- no production secrets;
- automatic teardown;
- optional fake/test backend where appropriate;
- clear preview banner;
- cost controls.

---

## PHASE FE-40 — Future external notification channels

### Objective

Extend persistent internal notifications into external delivery only after the internal model is stable.

### Candidate channels

- email;
- Slack;
- Discord;
- webhook.

### Rule

External delivery policy belongs on the backend. The Nuxt frontend configures preferences and displays delivery state; it is not the outbound delivery engine.

---


## PHASE FE-41 — Public Website / Landing Page

### Objective
Create a public-facing SynapseOS website that explains the product, demonstrates its differentiators, establishes trust, and routes visitors to the application, documentation, and GitHub repository.

### Why this exists
The private cockpit and the official documentation do not replace a product website. The landing page is responsible for positioning, conversion, product storytelling, SEO, and public trust.

### Technology
- Nuxt
- TypeScript
- Nuxt UI
- Tailwind CSS
- `@nuxtjs/i18n`
- Motion for Vue for restrained public-page motion
- GSAP only if a specific synchronized product demonstration genuinely needs it

### Target repository structure
```text
apps/
├── web/       # authenticated SynapseOS cockpit
├── docs/      # official documentation
└── website/   # public product website / landing page
```

Shared packages may be reused only where there is actual shared value:
```text
packages/
├── ui/
├── icons/
└── config/
```

### Required public sections
- Hero with a concise SynapseOS value proposition.
- Product problem / why SynapseOS exists.
- Core capability overview: agents, tasks, tools, skills, permissions, model routing, memory, context intelligence, observability.
- Interactive or animated product preview.
- Company Simulator preview.
- Kanban/task workflow preview.
- Developer → Reviewer corrective loop example.
- Security veto / bounded autonomy example.
- “How it works” sequence: Brief → Plan → Execute → Review → Validate → Deliver.
- Architecture/trust section explaining local + cloud models, provider neutrality, auditability, bounded autonomy, and permission enforcement.
- Developer section linking API, CLI when available, docs, and GitHub.
- Open-source/community section only if that remains part of SynapseOS positioning.
- CTA areas: Get Started, View Documentation, GitHub.

### Product demonstration rule
The landing page may contain a compact simulated demo, but it must demonstrate real SynapseOS concepts rather than meaningless decorative AI animation. A representative sequence may show:

```text
Developer Agent starts task
→ test fails
→ corrective iteration
→ tests pass
→ Reviewer receives evidence
→ Reviewer requests changes or approves
→ workflow reaches final state
```

The public demonstration may be pre-scripted for marketing performance, but must not misrepresent capabilities as production-ready if they are not actually available.

### SEO and sharing
- Semantic HTML.
- Metadata per route.
- Canonical URLs.
- Open Graph metadata.
- Social preview images.
- Sitemap.
- `robots.txt`.
- Structured data where useful and truthful.
- Strong Core Web Vitals targets.
- Public pages must remain indexable unless intentionally private.

### Performance rules
- Do not ship Vue Flow, D3, GSAP, ECharts, or large application-only dependencies to every landing page route unless needed by a specific section.
- Lazy-load heavy interactive demonstrations.
- Optimize media and fonts.
- Respect reduced-motion preferences.
- Avoid autoplay video with sound.

### Internationalization
- FR and EN from the first public release.
- Same canonical concept names as the application/documentation.
- No hardcoded business strings in reusable components.

### Analytics
Use privacy-conscious product/web analytics only after the analytics decision in FE-46 is implemented. Marketing analytics must remain separate conceptually from Sentry and OpenTelemetry.

### Tests
- Component tests for critical interactive sections.
- Playwright tests for navigation and CTAs.
- Accessibility tests.
- Broken-link checks.
- Metadata/SEO checks where practical.
- Performance smoke checks for regressions.

### Acceptance criteria
- Public website is clearly distinct from `apps/web` and `apps/docs`.
- Visitors can understand what SynapseOS is without authenticating.
- Product claims match implemented or clearly labeled upcoming capabilities.
- App, docs, and GitHub are reachable through visible CTAs.
- FR/EN, desktop, tablet, and mobile layouts work.
- Keyboard navigation and reduced-motion work.
- Production build passes independently.

### Deliberately out of scope initially
- Full CMS.
- Complex personalization.
- Marketing automation suite.
- Heavy animation solely for visual spectacle.
- Customer portal inside the public website.

### Definition of Done
The landing page can be deployed independently, is fast and accessible, clearly communicates SynapseOS, and does not duplicate the authenticated application or documentation responsibilities.

---

## PHASE FE-42 — Onboarding & First-Run Experience

### Objective
Guide a new user from first authentication to a usable SynapseOS workspace without requiring them to understand the entire architecture beforehand.

### Required flow
A first-run flow should progressively cover, when backend capabilities exist:

```text
Sign in
→ create/select organization or workspace
→ configure identity/profile basics
→ connect or select an LLM provider
→ verify provider health
→ select default model policy
→ create first project
→ understand agents/tasks/reviews at a glance
→ optionally launch a guided first workflow
```

### Principles
- Progressive disclosure instead of a 20-step setup wizard.
- Every setup step must correspond to a real backend state.
- Provider secrets must never be exposed back to the browser once stored securely.
- Users must be allowed to leave and resume onboarding.
- Existing users must not be forced back through first-run screens after completion.
- “Skip for now” is acceptable only when the omitted setup is genuinely optional.

### UI components
- Setup checklist.
- Provider health feedback.
- Workspace creation form.
- First-project template or blank-project choice.
- Contextual coach marks sparingly.
- “What is this?” links into official documentation.

### State
Persist onboarding completion/version server-side rather than only in `localStorage`, so the experience remains consistent across devices.

### Tests
- first login;
- interrupted onboarding + resume;
- invalid provider configuration;
- provider unavailable;
- permission-limited user;
- already-configured workspace;
- keyboard-only flow;
- FR/EN rendering.

### Acceptance criteria
A new authorized user can reach a functional first project without needing manual database changes or undocumented configuration.

### Deliberately out of scope initially
- Gamified onboarding.
- AI-generated personalized onboarding paths.
- Mandatory product tours for returning users.

### Definition of Done
First-run setup is resumable, secure, permission-aware, test-covered, and connected to real backend configuration.

---

## PHASE FE-43 — Account, Organization & Workspace Settings

### Objective
Provide explicit settings surfaces for personal preferences and organizational administration without mixing them with project execution screens.

### Settings domains
```text
Personal
├── profile
├── language
├── theme
├── timezone
├── notification preferences
└── keyboard preferences later

Organization / Workspace
├── name and metadata
├── members
├── roles
├── invitations if supported
├── defaults
├── provider visibility/policies
└── security/approval policies when authorized
```

### Authority rules
Authentik owns authentication identity concerns. SynapseOS owns domain authorization and workspace/project policy. The frontend must not invent roles or permissions independently.

### Sensitive settings
Provider credentials, security policy changes, permission elevation, and destructive workspace actions require stronger backend validation and confirmation patterns defined in the security section.

### Tests
- owner/admin/member permission differences;
- unauthorized route access;
- language/theme persistence;
- timezone rendering;
- update failures and optimistic-state rollback;
- destructive action confirmation.

### Acceptance criteria
Settings are grouped predictably, permission-aware, and do not expose secrets.

### Definition of Done
Users can manage supported personal and organizational preferences through backend-authoritative APIs with complete forbidden/error states.

---

## PHASE FE-44 — Empty, Loading, Error, Offline & Recovery States

### Objective
Make degraded and incomplete states first-class product behavior rather than afterthoughts.

### Required states
Every major feature must account for:
- initial loading;
- background refresh;
- empty collection;
- zero search results;
- forbidden/permission denied;
- not found;
- backend unavailable;
- provider unavailable;
- task/agent failed;
- SSE disconnected;
- SSE reconnecting;
- stale/reconciling state;
- session expired;
- maintenance/unavailable state;
- generic unexpected error.

### Public/system pages
At minimum provide designed experiences for:
- 403;
- 404;
- 500/unexpected failure;
- maintenance or temporarily unavailable;
- authentication/session expiration.

### UX rules
- Never use an endless spinner when an actionable error is known.
- Empty state must explain what is missing and provide the next valid action when possible.
- Recovery actions must be explicit: Retry, Reconnect, Refresh, Re-authenticate, View incident, etc.
- Realtime disconnect must not silently imply the displayed state is still current.
- Skeletons should preserve layout and avoid excessive motion.

### Tests
Failure-state coverage is mandatory in component and E2E tests for critical screens.

### Acceptance criteria
No critical screen has only a success-path design.

### Definition of Done
Loading, empty, forbidden, disconnected, and error states are deliberately designed and testable across the application.

---

## PHASE FE-45 — Feature Flags & Progressive Delivery

### Objective
Allow incomplete, experimental, risky, or staged capabilities to be enabled intentionally without long-lived code forks.

### Candidate uses
- Company Simulator V2.
- Memory UI.
- Context Intelligence visualizations.
- new provider integrations.
- advanced WebSocket interactions.
- experimental workflow views.

### Rules
- Flags must not be used as a substitute for authorization.
- Security checks remain backend-enforced even when a UI feature is hidden.
- Prefer server-controlled/environment-controlled flags for operational features.
- Flag names must be stable and documented.
- Every temporary flag must have an owner/removal condition.
- Tests must cover both enabled and disabled behavior for critical flags.

### Initial implementation
Start with a minimal typed flag layer; do not add a dedicated SaaS feature-flag vendor until operational complexity justifies it.

### Acceptance criteria
Experimental features can be disabled without code removal and without weakening backend policy.

### Definition of Done
Feature flags are typed, testable, documented, and cannot grant unauthorized capabilities.

---

## PHASE FE-46 — Product Analytics & Feedback

### Objective
Measure product usage and collect actionable feedback without conflating analytics with error monitoring or distributed tracing.

### Separation of responsibilities
```text
Sentry          → application errors / user-impacting failures
OpenTelemetry   → technical distributed traces/metrics
Product analytics → product usage patterns
Feedback        → explicit user reports/comments
```

### Privacy principles
- Data minimization.
- No provider API keys, secrets, prompt bodies, private source files, raw tool output, or credentials.
- Prefer event names and bounded metadata over payload capture.
- Respect applicable consent/privacy requirements.
- Session replay, if ever enabled, requires strong masking/redaction and a separate explicit decision.

### Useful events
Examples:
- project_created;
- run_started;
- kanban_view_opened;
- approval_completed;
- docs_opened_from_context;
- onboarding_completed;
- command_palette_used.

Do not record sensitive task content merely to understand feature usage.

### Feedback entry points
- Report a bug.
- Send product feedback.
- Link to GitHub issue flow where appropriate.
- Include bounded technical context only after user review/consent where necessary.

### Initial technology decision
No analytics vendor is mandated by this architecture. Choose a privacy-conscious implementation during this phase based on hosting/product needs at that time.

### Acceptance criteria
Analytics answers product questions without becoming a sensitive-data sink.

### Definition of Done
Product analytics and feedback have explicit schemas, privacy boundaries, and tests/redaction safeguards where applicable.

---

## PHASE FE-47 — Usage, Budgets & Billing Readiness

### Objective
Expose operational usage and budget information now while keeping commercial billing explicitly optional/deferred.

### V1 operational usage
The UI may surface, when backend data exists:
- token usage;
- model/provider usage;
- estimated/actual provider cost;
- project cost;
- agent/run cost;
- budget thresholds;
- budget warnings;
- provider quota/health signals where available.

### Billing boundary
Operational cost visibility is not the same as SaaS billing. Commercial plans, subscriptions, invoices, payment providers, taxes, and metering for customer billing are deliberately deferred until SynapseOS has a defined commercial model.

### UI
- usage dashboard;
- budget progress;
- cost trends through ECharts;
- filters by project/agent/provider/time period;
- warnings before configured limits;
- links to underlying runs when appropriate.

### Security
Billing or financial administration, if introduced later, requires separate permissions from ordinary usage visibility.

### Acceptance criteria
The product can explain its AI/runtime consumption without pretending a commercial billing system already exists.

### Deliberately deferred
- Stripe or other payment provider integration.
- subscriptions;
- plan enforcement;
- invoices;
- taxes;
- seat billing.

### Definition of Done
Usage/budget UI is operationally useful and commercial billing remains an explicit future decision.

---

## PHASE FE-48 — Public Status, Changelog & Release Experience

### Objective
Give users a trustworthy public view of service health and product evolution.

### Status experience
A public status surface may include:
- SynapseOS API status;
- authenticated web availability;
- documentation availability;
- major managed infrastructure components where relevant;
- incident timeline;
- maintenance notices;
- historical uptime only when data is reliable.

Do not expose internal topology, secrets, or security-sensitive diagnostics.

### Changelog
Provide a public changelog/release experience covering:
- new features;
- fixes;
- breaking changes;
- migrations;
- deprecations;
- security notices when public disclosure is appropriate;
- links to detailed docs/release notes.

### Source of truth
Prefer generating or curating changelog content from versioned release data rather than duplicating release facts in multiple places.

### Acceptance criteria
Users can distinguish an outage from a local problem and can understand what changed between releases.

### Definition of Done
Status and release communication have dedicated public surfaces with no leakage of sensitive operational details.

---

## PHASE FE-49 — Data Export / Import & Portability

### Objective
Provide bounded portability for user-owned/project data and operational reports.

### Candidate exports
Depending on backend support:
- project summaries;
- tasks;
- decisions;
- audit reports;
- run summaries;
- usage reports;
- configuration snapshots that exclude secrets;
- artifacts the user is authorized to access.

### Formats
Use explicit, documented formats such as JSON/CSV/ZIP/PDF only when they serve a real use case. Export schemas should be versioned when stability matters.

### Import
Import is more dangerous than export and should be introduced only for well-defined data types with schema validation, size limits, permission checks, and preview/dry-run where practical.

### Security rules
- No secret export by default.
- Permissions are revalidated at export time.
- Large exports use bounded asynchronous/backend flows when required.
- Audit sensitive export/import operations.

### Tests
- authorization;
- large dataset behavior;
- invalid import schemas;
- partial failure;
- redaction;
- cancellation/timeouts where supported.

### Acceptance criteria
Authorized users can retrieve supported data without bypassing project/workspace boundaries.

### Definition of Done
Export/import is schema-defined, bounded, permission-aware, and auditable.

---

## PHASE FE-50 — Legal, Privacy, Security & Public Trust Pages

### Objective
Provide the public trust and legal surfaces expected from a serious software platform without mixing legal content into product UI.

### Public pages to plan
- Privacy Policy.
- Terms of Service / Terms of Use when applicable.
- Security overview.
- Responsible disclosure / security contact process when available.
- Open-source / third-party licenses notices.
- Cookie/analytics disclosure if applicable.
- Data handling overview where appropriate.

### Security page
May explain high-level principles such as:
- bounded agent autonomy;
- permission enforcement;
- auditability;
- provider-neutral design;
- secret handling;
- responsible disclosure.

It must not reveal exploitable internal details.

### Legal content ownership
Legal text must not be fabricated by engineering as authoritative legal advice. The application provides the technical surface; finalized legal language must be reviewed by the appropriate owner before production use.

### Acceptance criteria
Public trust pages are discoverable from the website/footer and remain distinct from technical documentation.

### Definition of Done
Required public trust/legal routes exist, are version-controlled, accessible, and clearly owned for future legal review.

---

## Explicitly deferred product-surface decisions

The following are not forgotten; they are intentionally deferred until a concrete product requirement justifies them:

### PWA / installable application
- No PWA requirement for V1.
- Revisit only if offline capability, mobile installation, push notifications, or field use creates real value.
- Do not add service-worker complexity preemptively.

### White-label / deep theming
- The design system should remain tokenized and extensible.
- Full tenant-specific branding, custom domains, logos, or color systems are not a V1 requirement.

### Commercial SaaS billing
- Usage/cost visibility is planned in FE-47.
- Subscription/payment infrastructure remains separate and deferred.

### Fully configurable keyboard maps
- Keyboard-first navigation and Command Palette are required.
- User-remappable shortcut profiles are future scope.

### External support suite
- Feedback entry points are planned.
- A dedicated support/ticketing vendor is not required initially.

---

# 17. Testing strategy by layer

## 17.1 Unit tests — Vitest

Use for:

- pure data transforms;
- event routing;
- filter/query serialization;
- i18n mapping helpers;
- risk/status formatting;
- search/result mapping;
- metric aggregation;
- redaction utilities;
- stores/composables with isolated dependencies.

## 17.2 Component tests — Vue Test Utils

Use for:

- task cards;
- agent cards;
- drawers;
- notification center;
- table controls;
- forms;
- status components;
- accessible command palette behavior;
- error/loading/empty states.

## 17.3 E2E — Playwright

Critical workflows include:

- Authentik login/session;
- open/create project as supported;
- task management;
- allowed/denied state transition;
- Kanban move;
- SSE status update;
- run/review workflow;
- security veto;
- approval flow;
- provider-down/degraded experience;
- SSE reconnect;
- agent blocked;
- task failed;
- artifact upload/download once supported;
- logout/cache reset.

## 17.4 Failure testing is mandatory

Do not test only green paths. Include:

- 401 unauthenticated;
- 403 unauthorized;
- 404 stale/deleted entity;
- 409 conflict/concurrent transition where backend uses it;
- 422 validation;
- 5xx backend failure;
- network offline;
- SSE disconnected;
- provider unavailable;
- command timeout;
- run cancelled;
- artifact expired URL;
- partial metric data.

## 17.5 Accessibility testing

Automate what can be automated with axe/Playwright, but also manually verify:

- keyboard order;
- focus restoration;
- drag/drop alternative;
- screen-reader status text;
- reduced-motion;
- high-information tables/drawers.

---

# 18. Performance rules

Performance should be engineered from actual bottlenecks, not premature micro-optimization.

Baseline rules:

- paginate large server collections;
- virtualize only large list/table cases that need it;
- do not retain infinite SSE history in memory;
- lazy-load heavy visualization/terminal code where practical;
- avoid loading D3/GSAP/xterm on routes that never use them;
- debounce user search appropriately;
- cancel obsolete queries where supported;
- use image/file previews responsibly;
- aggregate graph data server-side when raw topology is too large;
- monitor actual Web Vitals/frontend spans through Sentry/OTel.

Company Simulator must remain responsive even when many backend events occur. Prefer event coalescing/aggregation over animating every low-level tool event.

---

# 19. Error and degraded-state UX

SynapseOS must distinguish failure types clearly.

Examples:

```text
Authentication expired
→ re-authentication path

Permission denied
→ explain missing permission/action not allowed

Provider degraded
→ show affected capability/provider status

SSE disconnected
→ show live-data degraded state and reconnect

Backend unavailable
→ global degraded banner + retry

Agent blocked
→ operational state, not frontend error

Security veto
→ explicit security state with evidence/link where allowed
```

Do not collapse all failures into “Something went wrong.”

Never expose raw stack traces to normal end users.

---

# 20. Security-sensitive UI copy and confidence semantics

The interface must not overclaim certainty.

For agent confidence/reputation/reliability:

- label the metric precisely;
- provide tooltip/help text;
- avoid “guaranteed”, “safe”, “correct” solely from score;
- show supporting state/evidence where available;
- distinguish model self-confidence from deterministic verification outcomes.

A reviewer approval, passing test, security scan, or permission check is a different signal from model confidence.

---

# 21. Deliberately deferred or conditional technologies

The following are **not forgotten**. They are intentionally deferred:

- **Meilisearch** — only when PostgreSQL search is insufficient;
- **WebSocket** — only for genuine bidirectional real-time interactions;
- **GSAP broad usage** — only for complex simulator choreography;
- **virtualization everywhere** — only on measured large-data surfaces;
- **preview environments** — after stable CI/staging/prod flow;
- **external notification channels** — after internal notification model;
- **complex docs versioning** — after real stable release versions;
- **advanced RAG/Memory visualization** — after backend memory contracts;
- **Context Intelligence dashboards** — after backend Context Intelligence Layer exists;
- **interactive arbitrary terminal** — not part of normal V1 and never a direct shell bypass;
- **Meilisearch for docs** — only after local/content search no longer satisfies needs;
- **custom authentication** — intentionally rejected in favor of Authentik;
- **Vuetify** — intentionally not selected as primary UI framework;
- **Next.js** — intentionally not selected for the main frontend;
- **fake Company Simulator animation** — explicitly prohibited.

---

# 22. Decision log / ADR index

This section captures the architecture choices in compact form. A future repo may convert each into individual ADR files if desired.

| ID | Decision | Status |
|---|---|---|
| ADR-FE-001 | Nuxt/Vue for the main frontend instead of Next.js/React | Accepted |
| ADR-FE-002 | TypeScript strict | Accepted |
| ADR-FE-003 | Nuxt UI + Tailwind instead of Vuetify as primary UI layer | Accepted |
| ADR-FE-004 | Pinia for client/UI state | Accepted |
| ADR-FE-005 | TanStack Query for server state | Accepted |
| ADR-FE-006 | REST for commands/CRUD | Accepted |
| ADR-FE-007 | SSE as primary live event transport | Accepted |
| ADR-FE-008 | WebSocket only for later genuine bidirectional needs | Accepted / Deferred |
| ADR-FE-009 | Vue Flow for Company Simulator/workflow graphs | Accepted |
| ADR-FE-010 | D3 for custom visualizations | Accepted |
| ADR-FE-011 | ECharts for standard analytics | Accepted |
| ADR-FE-012 | Motion for Vue as primary animation layer | Accepted |
| ADR-FE-013 | GSAP only for advanced synchronized simulator sequences | Accepted / Conditional |
| ADR-FE-014 | Authentik self-hosted via OIDC for authentication | Accepted |
| ADR-FE-015 | SynapseOS backend Permission Engine remains authorization authority | Accepted |
| ADR-FE-016 | Orval generates frontend API contracts from FastAPI OpenAPI | Accepted |
| ADR-FE-017 | Zod + vee-validate for frontend forms | Accepted |
| ADR-FE-018 | Vitest + Vue Test Utils + Playwright | Accepted |
| ADR-FE-019 | Sentry + OpenTelemetry observability with strict redaction | Accepted |
| ADR-FE-020 | xterm.js for technical logs/terminal-style views, never direct shell | Accepted |
| ADR-FE-021 | Lucide as primary standard icon set + custom SynapseOS domain icons | Accepted |
| ADR-FE-022 | Nuxt UI Command Palette + keyboard navigation | Accepted |
| ADR-FE-023 | PostgreSQL/FastAPI global search first | Accepted |
| ADR-FE-024 | Meilisearch only if later justified | Accepted / Deferred |
| ADR-FE-025 | Internal Notification Center + Nuxt UI toasts + SSE | Accepted |
| ADR-FE-026 | External email/Slack/Discord/webhook notifications later | Deferred |
| ADR-FE-027 | MinIO/S3-compatible object storage + PostgreSQL metadata | Accepted |
| ADR-FE-028 | Presigned URLs for suitable large browser uploads | Accepted |
| ADR-FE-029 | TanStack Table for data-heavy grids | Accepted |
| ADR-FE-030 | Kanban task view | Accepted |
| ADR-FE-031 | VueDraggable/SortableJS for Kanban DnD | Accepted |
| ADR-FE-032 | Backend TaskStateMachine controls all task transitions | Accepted |
| ADR-FE-033 | Kanban + Table + Timeline + Dependency Graph + Company View over same task truth | Accepted |
| ADR-FE-034 | `@nuxtjs/i18n` from V1, initially FR/EN | Accepted |
| ADR-FE-035 | Stored backend enums remain canonical/untranslated | Accepted |
| ADR-FE-036 | Dark-first Linear/Vercel/Supabase/GitLab-inspired design system | Accepted |
| ADR-FE-037 | Feature-first Nuxt architecture | Accepted |
| ADR-FE-038 | Separate `apps/web` and `apps/docs`, shared packages only when justified | Accepted |
| ADR-FE-039 | Zero-trust frontend; backend authoritative | Accepted |
| ADR-FE-040 | Desktop-first responsive strategy with mobile supervision mode | Accepted |
| ADR-FE-041 | WCAG 2.2 AA target + reduced motion | Accepted |
| ADR-FE-042 | Docker + GHCR + Traefik + HTTPS | Accepted |
| ADR-FE-043 | Development/staging/production isolation | Accepted |
| ADR-FE-044 | GitHub Actions CI/CD with separated concerns | Accepted |
| ADR-FE-045 | Staging automatic after valid main flow; production protected | Accepted |
| ADR-FE-046 | Immutable image tags + rollback | Accepted |
| ADR-FE-047 | PR preview environments later | Deferred |
| ADR-FE-048 | Official docs built with Nuxt + Nuxt Content + Nuxt UI + Tailwind | Accepted |
| ADR-FE-049 | Modern docs Command Palette/search | Accepted |
| ADR-FE-050 | Mermaid for docs architecture/workflow diagrams | Accepted |
| ADR-FE-051 | FastAPI OpenAPI → Scalar-style generated API reference | Accepted |
| ADR-FE-052 | Docs FR/EN and version-ready, no fake version complexity | Accepted |
| ADR-FE-053 | Dedicated docs CI/CD | Accepted |
| ADR-FE-054 | Company Simulator animations must map to real runtime state/events | Accepted |
| ADR-FE-055 | Company View, Control Center and Deep Inspect are distinct UX modes | Accepted |
| ADR-FE-056 | Daily Briefing derives from real system state/evidence | Accepted |

---

# 23. Implementation checklist template for every future frontend PR

Every implementation PR should answer these questions before merge:

```text
[ ] What single phase/objective does this PR implement?
[ ] Which backend contract is authoritative?
[ ] Which files were added/modified?
[ ] Which dependency was added and why is it necessary?
[ ] Was the dependency version locked through the project lockfile?
[ ] Are any secrets/public runtime values affected?
[ ] Are permissions enforced by backend, not just hidden in UI?
[ ] Are loading, empty, error and forbidden states implemented?
[ ] Are FR/EN strings added where user-facing text changed?
[ ] Is keyboard access preserved?
[ ] Does reduced-motion matter for this feature?
[ ] Are sensitive fields redacted from logs/Sentry/OTel?
[ ] Are unit/component/E2E tests added at the right level?
[ ] Did lint, typecheck, tests and production build pass?
[ ] Is documentation updated?
[ ] What is deliberately NOT implemented in this PR?
[ ] Are acceptance criteria demonstrably satisfied?
```

---

# 24. Common architecture mistakes to prevent globally

1. **Duplicating server state in Pinia.** TanStack Query owns remote cache.
2. **Implementing task state rules in the Kanban.** Backend `TaskStateMachine` owns transitions.
3. **Treating hidden buttons as authorization.** Backend Permission Engine owns permission.
4. **Putting provider API keys into Nuxt public runtime config.** Anything in client bundle is public.
5. **Using `localStorage` for long-lived sensitive tokens by default.** Prefer a safer server/session architecture.
6. **Opening multiple SSE streams per component.** Centralize/scoped event connection management.
7. **Assuming SSE is exactly-once.** Reconcile after reconnect and handle duplicates.
8. **Using WebSocket just because it sounds more real-time.** Use it only for bidirectional requirements.
9. **Using GSAP for every animation.** Motion for Vue is primary; GSAP is specialized.
10. **Using D3 for standard charts.** ECharts owns ordinary analytics.
11. **Using D3 to rebuild Vue Flow.** Vue Flow owns interactive workflow/org graphs.
12. **Making the simulator fictional.** Every meaningful visual state maps to real backend data.
13. **Rendering unbounded logs/events.** Use bounded histories, pagination/stream windows.
14. **Sending raw prompts/tool outputs to observability.** Redact/minimize.
15. **Storing large object bytes in PostgreSQL by default.** MinIO/S3 owns binaries; DB owns metadata.
16. **Uploading to MinIO with root credentials in the browser.** Use authorized presigned flows.
17. **Translating backend enum values.** Translate presentation labels only.
18. **Adding Meilisearch too early.** PostgreSQL search first.
19. **Building docs API reference manually.** Reuse FastAPI OpenAPI.
20. **Deploying production on every main commit without a gate.** Use protected promotion.
21. **Using only `latest` Docker tags.** Keep immutable SHA/version tags.
22. **Claiming accessibility from axe alone.** Manual keyboard/screen-reader validation still required.
23. **Forcing desktop simulator onto mobile.** Provide a supervision-oriented alternate view.
24. **Sharing production secrets/data with previews/staging.** Environments stay isolated.
25. **Extracting shared monorepo packages prematurely.** Extract only real shared code.

---

# 25. Completion audit — conversation decisions cross-check

This section was added specifically to verify that the architecture decisions agreed before writing this document were not lost during restructuring.

| Agreed item | Included in this document | Location |
|---|---:|---|
| Nuxt instead of Next.js | ✓ | §4.1, ADR-FE-001 |
| TypeScript | ✓ | §4.1, FE-1 |
| Nuxt UI + Tailwind instead of Vuetify | ✓ | §4.2, FE-2 |
| Pinia + TanStack Query responsibility split | ✓ | §4.3, FE-6/FE-7 |
| REST + SSE primary + WebSocket only if needed | ✓ | §4.5, FE-10, FE-37 |
| Vue Flow | ✓ | §4.6, FE-18 |
| D3 | ✓ | §4.7, FE-21 |
| Motion for Vue | ✓ | §4.9, FE-19 |
| GSAP only for complex sequences | ✓ | §4.9, FE-20 |
| ECharts | ✓ | §4.8, FE-17 |
| Authentik, Docker/self-hosted, OIDC | ✓ | §4.10, FE-8 |
| Authentication ≠ authorization | ✓ | §4.10, §9 |
| Orval from FastAPI OpenAPI | ✓ | §4.4, FE-5 |
| Zod + vee-validate | ✓ | §4.11, FE-9 |
| Vitest + Vue Test Utils + Playwright | ✓ | §4.12, §17 |
| Sentry + OpenTelemetry | ✓ | §4.13, FE-24/FE-25 |
| No prompts/secrets/raw sensitive output in traces | ✓ | §9.4, FE-24/25 |
| xterm.js | ✓ | §4.14, FE-16 |
| Timeline separate from raw terminal/logs | ✓ | §4.14, §14.3, FE-15/16 |
| Lucide + custom SynapseOS icons | ✓ | §4.15 |
| Nuxt UI Command Palette | ✓ | §4.16, FE-3 |
| Cmd/Ctrl+K and proposed keyboard shortcuts | ✓ | §4.16, §10 |
| PostgreSQL/FastAPI search first | ✓ | §5.1, FE-23 |
| Meilisearch only later if justified | ✓ | §5.1, FE-38 |
| Toast + persistent Notification Center + SSE | ✓ | §5.2, FE-11 |
| Notification severity INFO/WARNING/CRITICAL | ✓ | §5.2 |
| Email/Slack/Discord/Webhook later | ✓ | §5.2, FE-40 |
| MinIO S3-compatible storage | ✓ | §5.3, FE-22 |
| PostgreSQL stores file metadata | ✓ | §5.3, FE-22 |
| Presigned URLs | ✓ | §5.3, FE-22 |
| TanStack Table | ✓ | §5.4, FE-12 |
| Virtualization only when needed | ✓ | §5.4, §18 |
| Kanban like Trello/Jira | ✓ | §5.5, FE-14 |
| VueDraggable/SortableJS | ✓ | §5.5, FE-14 |
| Backend TaskStateMachine remains authoritative | ✓ | §1.2, §5.5, FE-13/14 |
| Kanban/Table/Timeline/Dependency/Company views | ✓ | §5.5 |
| `@nuxtjs/i18n` | ✓ | §6, FE-4 |
| FR + EN | ✓ | §6, docs §13 |
| Do not translate stored enums | ✓ | §6 |
| Dark-first design inspired by Linear/Vercel/Supabase/GitLab | ✓ | §3, §7 |
| Thin borders/minimal shadows/dense readable UI | ✓ | §3, §7 |
| Semantic agent animations | ✓ | §2.1, FE-18/19 |
| Available/working/blocked/reviewer/security visual semantics | ✓ | §2.1 |
| Agent card shows task/model/confidence/iteration/tool etc. | ✓ | §2.1, FE-18 |
| Daily Briefing from real state | ✓ | §2.1 |
| Company View + Control Center + Deep Inspect | ✓ | §2 |
| Feature-first architecture | ✓ | §8 |
| `apps/web` and `apps/docs` | ✓ | §8.1, §13 |
| shared packages only when justified | ✓ | §8.1 |
| CSP/XSS/cookies/CSRF/CORS/security headers | ✓ | §9 |
| no secrets/localStorage provider keys | ✓ | §9 |
| terminal never bypasses backend | ✓ | §9.5, FE-16 |
| LOW/MEDIUM/HIGH/CRITICAL confirmation concept | ✓ | §9.6 |
| Desktop-first responsive | ✓ | §10 |
| Mobile supervision experience | ✓ | §10.1 |
| WCAG 2.2 AA | ✓ | §10.2 |
| prefers-reduced-motion | ✓ | §10.3 |
| axe-core + Playwright | ✓ | §10.4, §17.5 |
| Docker + Docker Compose | ✓ | §11 |
| GHCR | ✓ | §11, §12 |
| Traefik preferred reverse proxy | ✓ | §11 |
| app/api/auth/docs host topology | ✓ | §11.2 |
| development/staging/production | ✓ | §11.3 |
| Nuxt private/public runtime config | ✓ | §11.4 |
| GitHub Actions separated workflows | ✓ | §12.1 |
| frontend CI exact quality stages | ✓ | §12.2 |
| backend pipeline remains separate | ✓ | §12.3 |
| cross-stack E2E with Authentik/MinIO as needed | ✓ | §12.4 |
| image SHA/version/latest tags | ✓ | §12.5 |
| automatic staging flow | ✓ | §12.6 |
| protected production gate | ✓ | §12.7 |
| rollback | ✓ | §12.8 |
| preview environments later | ✓ | §12.9, FE-39 |
| CI secrets protections | ✓ | §12.10 |
| SynapseOS later displays its own pipeline | ✓ | §12.11 |
| Official modern docs site | ✓ | §13 |
| Public Website / Landing Page | ✓ | FE-41 |
| Separate `apps/website` public surface | ✓ | FE-41 |
| Interactive product demonstration on landing page | ✓ | FE-41 |
| Landing SEO/Open Graph/performance/i18n | ✓ | FE-41 |
| Onboarding / first-run experience | ✓ | FE-42 |
| Account / organization / workspace settings | ✓ | FE-43 |
| Empty/loading/error/offline/recovery states | ✓ | FE-44 |
| 403/404/500/maintenance/session-expired pages | ✓ | FE-44 |
| Feature flags / progressive delivery | ✓ | FE-45 |
| Product analytics distinct from Sentry/OTel | ✓ | FE-46 |
| User feedback entry points | ✓ | FE-46 |
| Usage and budget visibility | ✓ | FE-47 |
| Commercial billing explicitly deferred | ✓ | FE-47 |
| Public status page | ✓ | FE-48 |
| Changelog / release experience | ✓ | FE-48 |
| Data export/import portability | ✓ | FE-49 |
| Legal/privacy/security/trust pages | ✓ | FE-50 |
| PWA deliberately deferred | ✓ | Explicitly deferred product-surface decisions |
| White-label deliberately deferred | ✓ | Explicitly deferred product-surface decisions |
| Configurable keyboard maps deferred | ✓ | Explicitly deferred product-surface decisions |
| Nuxt Content | ✓ | §13.1, FE-31 |
| Docs Command Palette | ✓ | §13.5, FE-32 |
| Docs search | ✓ | §13.9, FE-32 |
| Mermaid | ✓ | §13.11, FE-33 |
| OpenAPI → Scalar | ✓ | §13.8, FE-34 |
| Docs FR/EN | ✓ | §13.1, FE-35 |
| Docs version-ready | ✓ | §13.10, FE-35 |
| Product docs vs Engineering docs | ✓ | §13.7 |
| Docs CI with broken-link checks | ✓ | §13.12, FE-36 |
| Implementation phases with objective/install/config/files/rules/tests/errors/acceptance/exclusions | ✓ | §16 |
| One phase = one objective = one PR = one validation | ✓ | document header, §16 |
| Frontend should wait for sufficiently mature backend | ✓ | §1.1, FE-0 |

**Audit result:** all validated frontend decisions captured in the conversation, including the later product-surface audit (landing page, onboarding, settings, recovery states, feature flags, analytics/feedback, usage/billing readiness, status/changelog, portability, trust/legal pages, and explicit PWA/white-label deferrals), have a corresponding section or explicit deferred entry in this specification.

---

# 26. Final Definition of Done for the frontend architecture specification

This architecture specification is complete when:

- [x] product vision is defined;
- [x] Company View, Control Center and Deep Inspect are distinguished;
- [x] validated frontend stack is documented;
- [x] data/state ownership is documented;
- [x] API generation strategy is documented;
- [x] real-time strategy is documented;
- [x] authentication/authorization boundary is documented;
- [x] Kanban and task-state rules are documented;
- [x] storage/search/notification strategies are documented;
- [x] data visualization and motion responsibilities are documented;
- [x] security rules are documented;
- [x] accessibility/responsive strategy is documented;
- [x] build/deployment architecture is documented;
- [x] CI/CD is documented;
- [x] official documentation site is documented;
- [x] public marketing/landing website is documented;
- [x] onboarding and account/organization settings are documented;
- [x] loading/empty/error/offline/recovery states are documented;
- [x] feature-flag/progressive-delivery strategy is documented;
- [x] product analytics and feedback boundaries are documented;
- [x] usage/budget visibility and billing deferral are documented;
- [x] public status/changelog/release experience is documented;
- [x] data portability is documented;
- [x] legal/privacy/security trust surfaces are documented;
- [x] PWA, white-label and other deferred product surfaces are explicit;
- [x] deferred technologies are explicit;
- [x] implementation roadmap is phased;
- [x] testing strategy includes failure paths;
- [x] common architecture mistakes are explicit;
- [x] decisions are indexed in an ADR-style table;
- [x] a completion audit maps every previously validated decision to this document.

---

# 27. Intended repository integration

When GitHub write access is available, the intended integration is:

```text
branch: feature/frontend-architecture-roadmap
base:   the appropriate current backend branch/mainline at the time of integration
file:   docs/frontend-architecture-roadmap.md
```

Suggested commit:

```text
docs(frontend): add complete frontend architecture roadmap
```

Suggested PR title:

```text
docs(frontend): define SynapseOS frontend architecture and implementation roadmap
```

Suggested PR summary:

```text
- document the validated Nuxt frontend architecture
- define Company View, Control Center and Deep Inspect UX modes
- define state/API/realtime/auth/security/storage/search/notification decisions
- define Kanban and TaskStateMachine integration
- define testing, observability, accessibility and deployment requirements
- define GitHub Actions CI/CD and protected production promotion
- define the official Nuxt Content documentation site
- provide a phased implementation roadmap and ADR-style decision log
- keep deferred technologies explicit to avoid premature infrastructure
```

The branch should be created from the appropriate current integration base, not automatically from an unrelated stale `main` if stacked backend PRs are still the source of truth.

---

_End of specification._
