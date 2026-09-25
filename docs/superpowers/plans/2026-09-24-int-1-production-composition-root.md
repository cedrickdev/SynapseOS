# INT-1 Production Composition Root Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one fail-closed production composition root that creates the real Engineering V1 dependencies, gives every workflow run an isolated transaction and stage suite, and owns only the resources it creates.

**Architecture:** Keep `core/engineering_v1` provider-neutral. Add an application service that opens one SQLAlchemy session per run and obtains a fresh ordered stage suite from an injected factory. Infrastructure builds that factory from concrete PostgreSQL, Ollama, workspace, tool, Git, QA, Security, scoring, memory, feedback, and closure adapters; one async resource container owns the engine and network clients and is attached to FastAPI only through its lifespan.

**Tech Stack:** Python 3.12, FastAPI lifespan, Pydantic v2, pydantic-settings, SQLAlchemy 2, PostgreSQL, psycopg 3, httpx, pytest, Ruff, mypy.

**Spec:** `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md` — `PHASE 46`, `INT-1 — Production Composition Root`.

## Global Constraints

- Implement `INT-1` only; do not add durable queue models/workers, workflow HTTP commands, OIDC, frontend mutations, or deployment automation.
- Use English in source, comments, tests, branch names, commit messages, and new documentation.
- Use TDD: observe each focused test fail before adding its production implementation.
- Use real PostgreSQL initialized by Alembic for integration tests; never use `metadata.create_all()`.
- Preserve the existing Engineering V1 stage order, Security veto, Permission Engine, Autonomy Governor, human gates, append-only audit, and independent-review boundaries.
- Use one global workflow deadline, bounded stage/provider outputs, no implicit retry, no duplicate provider call, and immediate cancellation propagation.
- Persist no raw prompts, responses, provider exceptions, secrets, or unrestricted metadata.
- Reuse HTTP connections and close only resources created by the production root; injected clients remain caller-owned.
- Reject missing or ambiguous production configuration. Never substitute fake, in-memory, or permissive adapters in production.
- Do not modify `README.md`. Update only verified `INT-1` checklist boxes after all required checks pass.

## Review Focus

- Missing or placeholder production secrets must fail before the application becomes ready; Task 1 pins this behavior.
- An externally injected HTTP client must remain open after root shutdown; Task 2 pins ownership semantics.
- A missing concrete stage dependency must abort composition instead of installing a no-op stage; Task 3 pins this behavior.
- Concurrent runs must receive distinct sessions and mutable stage contexts; Task 6 pins run isolation.
- Cancellation or stage failure must roll back, close the session, preserve sanitized errors, and close no caller-owned dependency; Tasks 5 and 6 pin cleanup.

---

### Task 1: Fail-closed production settings

**Files:**
- Create: `core/production/__init__.py`
- Create: `core/production/errors.py`
- Create: `core/production/settings.py`
- Modify: `core/config.py`
- Modify: `.env.example`
- Test: `tests/production/test_settings.py`

**Interfaces:**
- Consumes: `core.config.Settings`.
- Produces: `ProductionConfigurationError`, immutable `ProductionSettings`, and
  `validate_production_settings(settings: Settings) -> ProductionSettings`.

- [ ] **Step 1: Write failing validation tests**

```python
def test_production_settings_reject_placeholder_credentials() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://synapseos:change-me@db:5432/synapseos",
        github_service_token=SecretStr("replace-me"),
    )

    with pytest.raises(ProductionConfigurationError):
        validate_production_settings(settings)


def test_production_settings_require_exactly_one_github_auth_strategy() -> None:
    with pytest.raises(ProductionConfigurationError):
        validate_production_settings(_production_settings(github_service_token=None))
```

Also cover a non-PostgreSQL URL, credential-bearing provider base URLs, blank model names,
unbounded limits, simultaneous service-token and GitHub-App credentials, and valid service-token
and GitHub-App configurations.

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `.venv/bin/pytest tests/production/test_settings.py -q`

Expected: collection fails because `core.production.settings` does not exist.

- [ ] **Step 3: Add the minimum strict settings boundary**

```python
class ProductionSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    database_url: str
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: float
    ollama_max_response_bytes: int
    github_base_url: str
    github_max_response_bytes: int
    github_service_token: SecretStr | None
    github_app_id: int | None
    github_installation_id: int | None
    github_app_private_key: SecretStr | None
    workspace_base_root: Path
    git_executable: Path
    engineering_v1_timeout_seconds: float
```

Add the corresponding optional/raw environment fields to `Settings`; only
`validate_production_settings()` turns them into required production values. Reject known example
placeholders and unsafe URL forms without including secret values in exceptions.

- [ ] **Step 4: Run the focused tests to GREEN**

Run: `.venv/bin/pytest tests/production/test_settings.py -q`

Expected: all settings tests pass with sanitized errors.

- [ ] **Step 5: Commit the settings boundary**

```bash
git add core/production core/config.py .env.example tests/production/test_settings.py
git commit -m "feat(production): validate composition settings"
```

### Task 2: Explicit resource ownership container

**Files:**
- Create: `infrastructure/production/__init__.py`
- Create: `infrastructure/production/resources.py`
- Test: `tests/production/test_resources.py`

**Interfaces:**
- Consumes: `ProductionSettings`, optional caller-owned `httpx.AsyncClient`, SQLAlchemy
  `create_engine`, `OllamaLLMProvider`, and `build_github_provider`.
- Produces: `ProductionResources`,
  `build_production_resources(settings, *, http_client=None) -> ProductionResources`, and
  idempotent `await ProductionResources.aclose()`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_shutdown_does_not_close_injected_http_client(valid_settings: ProductionSettings) -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(_ok_response))
        resources = build_production_resources(valid_settings, http_client=client)
        await resources.aclose()
        await resources.aclose()
        assert not client.is_closed
        await client.aclose()

    asyncio.run(scenario())
```

Also prove an internally created client and engine are closed once, partial construction cleans up
already-created resources, and no connection is opened merely by importing the module.

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `.venv/bin/pytest tests/production/test_resources.py -q`

Expected: collection fails because `infrastructure.production.resources` is missing.

- [ ] **Step 3: Implement one idempotent resource owner**

```python
class ProductionResources:
    def __init__(
        self,
        *,
        engine: Engine,
        session_factory: sessionmaker[Session],
        http_client: httpx.AsyncClient,
        owns_http_client: bool,
        llm_provider: OllamaLLMProvider,
        github: GitHubProviderResources,
    ) -> None: ...

    async def aclose(self) -> None: ...
```

Construct the SQLAlchemy engine from the validated URL instead of importing the module-global
engine. Inject the shared client into Ollama and GitHub so those adapters retain caller-owned
lifecycle behavior. Close GitHub and Ollama wrappers before the owned client, then dispose the
engine.

- [ ] **Step 4: Run the focused tests to GREEN**

Run: `.venv/bin/pytest tests/production/test_resources.py -q`

- [ ] **Step 5: Commit resource ownership**

```bash
git add infrastructure/production tests/production/test_resources.py
git commit -m "feat(production): own runtime resources"
```

### Task 3: Per-run stage-suite contracts and context loading

**Files:**
- Modify: `core/engineering_v1/ports.py`
- Create: `core/engineering_v1/application.py`
- Create: `infrastructure/engineering_v1/context.py`
- Create: `infrastructure/engineering_v1/stages.py`
- Modify: `core/engineering_v1/__init__.py`
- Modify: `infrastructure/engineering_v1/__init__.py`
- Test: `tests/engineering_v1/test_application.py`
- Test: `tests/database/test_engineering_v1_context.py`

**Interfaces:**
- Produces: `EngineeringStageSuite.ordered_stages() -> tuple[EngineeringStageRunner, ...]` and
  `EngineeringStageSuiteFactory.create(session: Session) -> EngineeringStageSuite`.
- Produces: immutable `EngineeringRunSnapshot` containing only bounded project/task/agent/workspace
  identifiers and safe textual fields loaded from PostgreSQL.
- Produces: `SQLAlchemyEngineeringContextLoader.load(request) -> EngineeringRunSnapshot`.
- Produces: one fresh `ProductionEngineeringStageSuite` per invocation; its
  `ordered_stages() -> tuple[EngineeringStageRunner, ...]` exactly matches
  `ENGINEERING_V1_STAGE_ORDER`.

- [ ] **Step 1: Write failing contract and PostgreSQL tests**

```python
def test_stage_factory_returns_exact_order_with_no_missing_stage(db_session: Session) -> None:
    suite = factory.create(db_session)
    stages = suite.ordered_stages()
    assert tuple(item.stage for item in stages) == ENGINEERING_V1_STAGE_ORDER


def test_context_loader_rejects_cross_project_task(db_session: Session) -> None:
    request = _request(project_id=project_a.id, task_id=project_b_task.id)
    with pytest.raises(EngineeringV1Error) as raised:
        SQLAlchemyEngineeringContextLoader(db_session).load(request)
    assert raised.value.code is EngineeringV1ErrorCode.INVALID_INPUT
```

Also test missing project/task, unassigned execution-stage agent, oversized unsafe persisted text,
and two calls returning separate mutable execution contexts.

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/engineering_v1/test_application.py tests/database/test_engineering_v1_context.py -q`

- [ ] **Step 3: Add the stage factory and bounded loader**

```python
class EngineeringStageSuite(Protocol):
    def ordered_stages(self) -> tuple[EngineeringStageRunner, ...]: ...


class EngineeringStageSuiteFactory(Protocol):
    def create(self, session: Session) -> EngineeringStageSuite: ...


@dataclass(frozen=True, slots=True)
class EngineeringRunSnapshot:
    project_id: UUID
    task_id: UUID
    project_name: str
    specification: str
    task_title: str
    task_description: str
    acceptance_criteria: tuple[str, ...]
    assigned_agent_id: UUID | None
```

The suite owns ephemeral outputs for its single run only. It may pass typed outputs between stages
in memory, but it must never persist raw prompts/responses or share state with another run. Factory
construction must fail if any concrete stage adapter is absent; no no-op fallback is permitted.

- [ ] **Step 4: Run the focused tests to GREEN**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/engineering_v1/test_application.py tests/database/test_engineering_v1_context.py -q`

- [ ] **Step 5: Commit stage-suite contracts**

```bash
git add core/engineering_v1 infrastructure/engineering_v1 tests/engineering_v1 tests/database/test_engineering_v1_context.py
git commit -m "feat(engineering-v1): add production stage suite"
```

### Task 4: Compose the real Engineering V1 stage adapters

**Files:**
- Create: `infrastructure/engineering_v1/planning_stages.py`
- Create: `infrastructure/engineering_v1/delivery_stages.py`
- Create: `infrastructure/engineering_v1/completion_stages.py`
- Modify: `infrastructure/engineering_v1/stages.py`
- Test: `tests/engineering_v1/test_production_stages.py`
- Test: `tests/database/test_engineering_v1_production_stages.py`

**Interfaces:**
- Planning adapters consume `IntakeAgent`, `ArchitectureAgent`, `DomainDecomposer`, and persisted
  agent-registry data for `SPECIFICATION_ANALYSIS` through `AGENT_ASSIGNMENT`.
- Delivery adapters consume the existing workspace, Developer–Reviewer, QA, Security, Git workflow,
  and merge-gate services for `REPOSITORY_INSPECTION` through `MERGE_GATE`.
- Completion adapters consume append-only audit, reputation/scoring, memory, feedback, and closure
  services for `AUDIT` through `CLOSURE`.
- Every adapter returns only `EngineeringStageEvidence(stage, passed, evidence_ids)`; rich outputs
  remain ephemeral or in their already-approved authoritative stores.

- [ ] **Step 1: Write failing stage behavior tests**

```python
def test_security_block_prevents_merge_gate_and_completion(stage_suite) -> None:
    async def scenario() -> None:
        stages = stage_suite.with_security_result(passed=False).ordered_stages()
        result = await EngineeringV1Orchestrator(stages, audit).run(request)
        assert result.blocked_stage is EngineeringStage.SECURITY
        assert merge_gate.calls == 0

    asyncio.run(scenario())


def test_developer_reviewer_workflow_is_invoked_once(stage_suite) -> None:
    asyncio.run(_run_through(EngineeringStage.INDEPENDENT_REVIEW, stage_suite))
    assert developer_reviewer.calls == 1
```

Add one focused test for every stage, plus tests proving cached results do not duplicate Intake,
Developer–Reviewer, QA, Security, or provider calls. Verify deterministic tool evidence outranks
LLM claims and that a missing human gate yields `passed=False` rather than a bypass.

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `.venv/bin/pytest tests/engineering_v1/test_production_stages.py -q`

- [ ] **Step 3: Implement planning adapters**

```python
class SpecificationAnalysisStage:
    stage = EngineeringStage.SPECIFICATION_ANALYSIS

    async def run(self, request, completed):
        result = await self._state.intake_once(request)
        return _evidence(self.stage, passed=True, ids=result_evidence_ids(result))
```

`BLOCKING_QUESTIONS` reuses the exact intake result and blocks when readiness is
`WAITING_FOR_CLIENT`. `ARCHITECTURE` reuses intake and blocks on required escalation.
`TASK_PLANNING` calls `DomainDecomposer` once. `AGENT_ASSIGNMENT` uses only persisted eligible
agents and the existing deterministic matcher/manager authority chain.

- [ ] **Step 4: Implement delivery adapters**

Invoke the existing Developer–Reviewer workflow once and expose its repository inspection, code,
test, and independent-review evidence without repeating provider/tool work. Run QA and Security
through their existing PostgreSQL workflows. Evaluate the existing merge gate only after fresh
Reviewer, QA, Security, status-check, and head-SHA evidence is available. Remote merge execution
remains behind its existing explicit command boundary.

- [ ] **Step 5: Implement completion adapters**

Require correlated audit evidence before scoring. Record only approved bounded reputation and
memory data. Treat absent optional client feedback as an explicit content-free evidence outcome,
not invented feedback. Run closure only after all mandatory completion preconditions are persisted.

- [ ] **Step 6: Run focused unit and PostgreSQL tests to GREEN**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/engineering_v1/test_production_stages.py tests/database/test_engineering_v1_production_stages.py -q`

- [ ] **Step 7: Commit real stage adapters**

```bash
git add infrastructure/engineering_v1 tests/engineering_v1/test_production_stages.py tests/database/test_engineering_v1_production_stages.py
git commit -m "feat(engineering-v1): compose production stages"
```

### Task 5: Transactional Engineering V1 application service

**Files:**
- Modify: `core/engineering_v1/application.py`
- Modify: `infrastructure/engineering_v1/composition.py`
- Test: `tests/engineering_v1/test_application.py`
- Test: `tests/database/test_engineering_v1_application.py`

**Interfaces:**
- Produces: `EngineeringV1Application.run(request: EngineeringV1Request) -> EngineeringV1Result`.
- Consumes: `sessionmaker[Session]` and `EngineeringStageSuiteFactory`.
- Replaces public production use of the caller-supplied `Mapping[EngineeringStage,
  EngineeringStageOperation]`. Retain the existing helper as a compatibility boundary for its
  current focused tests, but production composition must never call it.

- [ ] **Step 1: Write failing transaction and cancellation tests**

```python
def test_application_rolls_back_and_closes_on_cancellation(session_factory, factory) -> None:
    async def scenario() -> None:
        operation = asyncio.create_task(
            EngineeringV1Application(session_factory, factory).run(request)
        )
        await factory.wait_until_active()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert factory.session_rolled_back
        assert factory.session_closed

    asyncio.run(scenario())
```

Also prove successful and deterministically blocked flows commit once, failures roll back once,
sanitized domain errors escape, and no application path retries a stage.

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/engineering_v1/test_application.py tests/database/test_engineering_v1_application.py -q`

- [ ] **Step 3: Implement the transaction boundary**

```python
class EngineeringV1Application:
    def __init__(self, session_factory, stage_factory) -> None: ...

    async def run(self, request: EngineeringV1Request) -> EngineeringV1Result:
        session = self._session_factory()
        try:
            suite = self._stage_factory.create(session)
            result = await EngineeringV1Orchestrator(
                suite.ordered_stages(),
                SQLAlchemyEngineeringAuditSink(session),
            ).run(request)
            session.commit()
            return result
        except asyncio.CancelledError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

Canonicalize exceptions before they cross the application boundary; never include provider,
database, prompt, path, or credential details.

- [ ] **Step 4: Run focused tests to GREEN**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/engineering_v1/test_application.py tests/database/test_engineering_v1_application.py -q`

- [ ] **Step 5: Commit the application boundary**

```bash
git add core/engineering_v1/application.py infrastructure/engineering_v1/composition.py tests/engineering_v1/test_application.py tests/database/test_engineering_v1_application.py
git commit -m "feat(engineering-v1): add transactional application"
```

### Task 6: Complete production construction and run isolation

**Files:**
- Modify: `infrastructure/production/resources.py`
- Create: `infrastructure/production/composition.py`
- Test: `tests/production/test_composition.py`
- Test: `tests/database/test_production_composition.py`

**Interfaces:**
- Produces: `build_production_application(settings, *, http_client=None) -> ProductionResources`.
- `ProductionResources.engineering_v1` is a fully composed `EngineeringV1Application` requiring no
  caller-supplied stage operation map.

- [ ] **Step 1: Write failing full-composition tests**

```python
def test_root_exposes_fully_composed_application(valid_settings) -> None:
    resources = build_production_application(valid_settings, http_client=client)
    assert isinstance(resources.engineering_v1, EngineeringV1Application)


def test_concurrent_runs_do_not_share_sessions_or_stage_state(resources) -> None:
    async def scenario() -> None:
        first, second = await asyncio.gather(
            resources.engineering_v1.run(first_request),
            resources.engineering_v1.run(second_request),
        )
        assert first.correlation_id != second.correlation_id
        assert resources.stage_factory.created_contexts_are_distinct

    asyncio.run(scenario())
```

Also assert fail-closed construction when a required adapter cannot be built, one shared network
client, fresh session/stage suite per run, and exact provider/client ownership on shutdown.

- [ ] **Step 2: Run focused tests and observe RED**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/production/test_composition.py tests/database/test_production_composition.py -q`

- [ ] **Step 3: Construct the concrete dependency graph**

Build existing adapters in authority order: audit and PostgreSQL repositories; Permission Engine;
Autonomy Governor; workspace and fixed-profile tools; Developer/Reviewer/QA/Security workflows;
Git provider and merge gate; scoring, memory, feedback, closure; ordered stage factory; transactional
application. Do not expose individual privileged adapters through the public resource container.

- [ ] **Step 4: Run focused tests to GREEN**

Run: `TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/production/test_composition.py tests/database/test_production_composition.py -q`

- [ ] **Step 5: Commit production construction**

```bash
git add infrastructure/production tests/production/test_composition.py tests/database/test_production_composition.py
git commit -m "feat(production): compose engineering v1"
```

### Task 7: FastAPI lifespan integration without new workflow routes

**Files:**
- Create: `apps/api/lifecycle.py`
- Modify: `apps/api/main.py`
- Test: `tests/api/test_lifecycle.py`

**Interfaces:**
- Produces: `production_lifespan(settings, resource_factory)` for `FastAPI(lifespan=...)`.
- Stores only the high-level `ProductionResources` handle on `app.state`; no new route is added in
  `INT-1`.

- [ ] **Step 1: Write failing startup/shutdown tests**

```python
def test_production_startup_fails_closed_when_composition_fails() -> None:
    app = create_app(settings=_production_settings(), production_factory=_failing_factory)
    with pytest.raises(ProductionConfigurationError):
        with TestClient(app):
            pass


def test_lifespan_closes_resources_once() -> None:
    resources = RecordingResources()
    app = create_app(settings=_production_settings(), production_factory=lambda _: resources)
    with TestClient(app):
        assert app.state.production_resources is resources
    assert resources.close_calls == 1
```

Also prove development/test startup does not silently instantiate production resources and an
injected resource factory remains injectable without transferring client ownership.

- [ ] **Step 2: Run focused tests and observe RED**

Run: `.venv/bin/pytest tests/api/test_lifecycle.py tests/test_health.py -q`

- [ ] **Step 3: Add explicit lifespan wiring**

```python
@asynccontextmanager
async def production_lifespan(app: FastAPI):
    settings = app.state.settings
    if settings.app_env == "production":
        resources = app.state.production_factory(validate_production_settings(settings))
        app.state.production_resources = resources
        try:
            yield
        finally:
            await resources.aclose()
    else:
        yield
```

Keep health, metrics, and existing dashboard routes unchanged. `INT-3` will add workflow commands;
`INT-4` will replace human-facing authentication.

- [ ] **Step 4: Run focused tests to GREEN**

Run: `.venv/bin/pytest tests/api/test_lifecycle.py tests/test_health.py -q`

- [ ] **Step 5: Commit lifespan integration**

```bash
git add apps/api/lifecycle.py apps/api/main.py tests/api/test_lifecycle.py
git commit -m "feat(api): initialize production resources"
```

### Task 8: Full verification and INT-1 delivery

**Files:**
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`
- Do not modify: `README.md`

**Interfaces:**
- Produces a verified `INT-1` branch and leaves `INT-2` through `INT-7` untouched.

- [ ] **Step 1: Run focused INT-1 verification**

Run:

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest \
  tests/production \
  tests/engineering_v1 \
  tests/database/test_engineering_v1_context.py \
  tests/database/test_engineering_v1_production_stages.py \
  tests/database/test_engineering_v1_application.py \
  tests/database/test_production_composition.py \
  tests/api/test_lifecycle.py -q
```

Expected: all focused tests pass with no warnings.

- [ ] **Step 2: Run complete quality gates**

Run:

```bash
TEST_POSTGRES_PORT=55432 make test
make lint
.venv/bin/ruff format --check .
make typecheck
```

Expected: complete pytest, Ruff lint, Ruff format, and strict mypy pass.

- [ ] **Step 3: Verify scope and secrets**

Run:

```bash
git diff --check origin/phase-42/queue-concurrency...HEAD
git diff --name-only origin/phase-42/queue-concurrency...HEAD
git diff --exit-code origin/phase-42/queue-concurrency...HEAD -- README.md
rg -n "replace-me|change-me|BEGIN .*PRIVATE KEY|github_pat_" \
  core infrastructure apps tests .env.example
```

Expected: no diff errors, no README change, no `INT-2` implementation, and no real credential.
Example placeholders are allowed only in `.env.example` and tests that explicitly validate their
rejection.

- [ ] **Step 4: Update only verified INT-1 checkboxes**

Check each `INT-1` item only after its corresponding test and quality gate has passed. Leave every
`INT-2` through `INT-7` item unchecked.

- [ ] **Step 5: Commit, push, review, and merge**

```bash
git add SYNAPSEOS_DEVELOPMENT_CHECKLIST.md
git commit -m "docs(roadmap): complete production composition"
git push -u origin phase-46/production-composition-root
```

Open one PR targeting `phase-42/queue-concurrency`, run an independent whole-branch review,
resolve findings, verify required checks, merge in order, and synchronize that integration branch.
