# Phase 18 Security Agent V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one bounded independent Security Agent and one audited security workflow stage that
reviews sanitized code evidence, applies a deterministic veto, and advances `WAITING_SECURITY` to
`COMPLETED`, `CHANGES_REQUESTED`, or fail-closed `WAITING_HUMAN`.

**Architecture:** Add a strict `core/security/` application package that validates independent
Security authority, redacts obvious secrets locally, invokes one injected scanner suite, performs
one provider-neutral analysis, and applies a deterministic `PASS`/`WARN`/`BLOCK` gate. Add a
separate `core/workflows/security_*` stage that validates persistent Developer/Reviewer/QA/Security
scope, records append-only checkpoints, invokes Security once, and commits an existing
`TaskStateMachine` transition. Preserve all Phase 17 public contracts and do not implement external
scanner adapters or Phase 19 Git workflow behavior.

**Tech Stack:** Python 3.12+, Pydantic v2, asyncio, existing `LLMProvider`, existing tool and
permission contracts, SQLAlchemy 2, PostgreSQL, Alembic-managed test schema, pytest, Ruff, and
strict mypy.

**Spec:** `docs/superpowers/specs/2026-09-01-phase-18-security-agent-design.md`

## Global Constraints

- Implement Phase 18 only; do not add Git workflow, merge automation, deployment, or Phase 19
  behavior.
- Use English for source, comments, docstrings, documentation, branch names, and commits.
- Follow RED-GREEN-REFACTOR: observe every new production behavior failing before implementing it.
- PostgreSQL tests use the real Alembic-built schema and never `metadata.create_all()`.
- Security identity must differ from Developer, Reviewer, and QA identities.
- Security has autonomy level zero or one, read-only authority, and no shell, write, merge,
  deployment, production, permission-mutation, or secret-value access.
- `WARN` always maps to `WAITING_HUMAN`; uncertainty never maps to `COMPLETED`.
- A trusted confirmed `HIGH` or `CRITICAL` finding forces `BLOCK` regardless of provider output.
- Provider findings cannot self-confirm; provider-only blocking claims become `WARN` unless matched
  by trusted deterministic evidence.
- Run the scanner suite once and the provider once; no implicit retry, fallback, duplicate call, or
  speculative concurrency.
- Every timeout, string, source file, aggregate source set, diff, collection, scanner result,
  provider response, result, error, and audit value is explicitly bounded.
- Cancellation propagates immediately and injected resources remain caller-owned.
- Raw source, diff, secrets, scanner output, prompts, responses, and arbitrary provider metadata are
  never persisted automatically.
- Deterministic scanner, QA, and test evidence outrank provider self-assessment.
- Preserve the existing task-state graph; required Phase 18 transitions already exist.
- Do not add Semgrep, Trivy, ZAP, a free-form command runner, MCP, memory, reputation, or a generic
  control-stage framework.

---

### Task 1: Strict Security contracts and safe errors

**Files:**
- Create: `core/security/__init__.py`
- Create: `core/security/types.py`
- Create: `core/security/errors.py`
- Create: `tests/security/__init__.py`
- Create: `tests/security/factories.py`
- Create: `tests/security/test_types.py`
- Create: `tests/security/test_errors.py`

**Interfaces:**
- Consumes: `AgentProfile`, `QAResult`, `QATestEvidence`, and `ToolExecutionContext`.
- Produces: `SecurityDecision`, `SecuritySeverity`, `SecurityConfirmation`,
  `SecuritySourceFile`, `SecurityEvidenceReference`, `SecurityFinding`,
  `SecurityAnalysisFinding`, `SecurityScannerFinding`, `SecurityScannerReport`,
  `SanitizedSecuritySource`, `SecurityAnalysis`, `SecurityRequest`,
  `SecurityScannerSummary`, `SecurityResult`, `SecurityErrorCode`, and `SecurityError`.

- [ ] **Step 1: Write failing immutable-contract tests**

Create tests for strict nested revalidation, tuple copying, unknown-field rejection, hidden input
errors, normalized relative paths, finite confidence and duration values, bounded line ranges,
unique evidence references, distinct role identities, truthful QA/test scope, aggregate source-byte
limits, and truthful result shapes.

```python
def test_request_rejects_duplicate_or_inconsistent_test_evidence() -> None:
    evidence = successful_qa_test_evidence()
    with pytest.raises(ValidationError):
        security_request(tests=(evidence, evidence))


def test_block_result_requires_confirmed_high_impact_finding() -> None:
    with pytest.raises(ValidationError):
        SecurityResult(
            decision=SecurityDecision.BLOCK,
            findings=(suspected_finding(SecuritySeverity.CRITICAL),),
            scanner=complete_scanner_summary(),
            uncertainty_reasons=(),
            rationale="The proposed block lacks deterministic confirmation.",
            confidence=0.95,
            correlation_id=CORRELATION_ID,
        )
```

- [ ] **Step 2: Run focused tests and observe RED**

```bash
.venv/bin/pytest tests/security/test_types.py tests/security/test_errors.py -q
```

Expected: test collection fails because `core.security` does not exist.

- [ ] **Step 3: Implement exact enums and immutable models**

Use `ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True,
revalidate_instances="always")`. Keep Security-specific enums in `core/security/types.py`.

```python
class SecurityDecision(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class SecuritySeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityConfirmation(StrEnum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
```

Define these exact public shapes:

```python
class SecuritySourceFile(_ImmutableSecurityModel):
    path: RelativePath
    content: Annotated[str, Field(min_length=1, max_length=16_384)]


class SecurityEvidenceReference(_ImmutableSecurityModel):
    source_id: Identifier
    evidence_id: Identifier


class SecurityFinding(_ImmutableSecurityModel):
    category: Identifier
    severity: SecuritySeverity
    path: RelativePath | None = None
    line_start: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    line_end: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    explanation: Text4096
    remediation: Text4096
    confidence: UnitScore
    evidence: Annotated[tuple[SecurityEvidenceReference, ...], Field(min_length=1, max_length=8)]
    confirmation: SecurityConfirmation


class SecurityAnalysisFinding(_ImmutableSecurityModel):
    category: Identifier
    severity: SecuritySeverity
    path: RelativePath | None = None
    line_start: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    line_end: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    explanation: Text4096
    remediation: Text4096
    confidence: UnitScore
    evidence_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=8)]


class SecurityScannerFinding(SecurityFinding):
    """Sanitized deterministic evidence emitted by the scanner boundary."""


class SecurityScannerReport(_ImmutableSecurityModel):
    suite_id: Identifier
    findings: Annotated[tuple[SecurityScannerFinding, ...], Field(max_length=64)]
    complete: bool
    truncated: bool
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


class SanitizedSecuritySource(_ImmutableSecurityModel):
    diff: Annotated[str, Field(min_length=1, max_length=16_384)]
    files: Annotated[tuple[SecuritySourceFile, ...], Field(min_length=1, max_length=16)]
    findings: Annotated[tuple[SecurityScannerFinding, ...], Field(max_length=64)]
    complete: bool


class SecurityAnalysis(_ImmutableSecurityModel):
    decision: SecurityDecision
    findings: Annotated[tuple[SecurityAnalysisFinding, ...], Field(max_length=64)]
    uncertainty_reasons: Annotated[tuple[Text1024, ...], Field(max_length=16)]
    rationale: Text16384
    confidence: UnitScore


class SecurityRequest(_ImmutableSecurityModel):
    task_id: UUID
    project_id: UUID
    developer_id: Identifier
    reviewer_id: Identifier
    qa_id: Identifier
    security_id: Identifier
    profile: AgentProfile
    task_title: Text255
    task_description: Text8192
    acceptance_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=16)]
    diff: Annotated[str, Field(min_length=1, max_length=16_384)]
    affected_files: Annotated[tuple[SecuritySourceFile, ...], Field(min_length=1, max_length=16)]
    qa_result: QAResult
    tests: Annotated[tuple[QATestEvidence, ...], Field(min_length=1, max_length=3)]
    execution_context: ToolExecutionContext
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0, allow_inf_nan=False)]
    correlation_id: UUID


class SecurityScannerSummary(_ImmutableSecurityModel):
    suite_id: Identifier
    complete: bool
    truncated: bool
    finding_count: Annotated[int, Field(ge=0, le=64)]
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


class SecurityResult(_ImmutableSecurityModel):
    decision: SecurityDecision
    findings: Annotated[tuple[SecurityFinding, ...], Field(max_length=64)]
    scanner: SecurityScannerSummary
    uncertainty_reasons: Annotated[tuple[Text1024, ...], Field(max_length=16)]
    rationale: Text16384
    confidence: UnitScore
    correlation_id: UUID
```

Model validators must require ordered line ranges, unique normalized file paths, no duplicate
evidence references, four distinct role slugs, `qa_result.decision is PASSED`, exact equality
between `tests` and `qa_result.tests`, matching correlation IDs, an aggregate affected-source limit
of 65,536 UTF-8 bytes, and truthful decision shapes:

- `PASS`: no findings, no uncertainty, complete non-truncated scanner summary;
- `WARN`: at least one finding or uncertainty reason;
- `BLOCK`: at least one confirmed `HIGH` or `CRITICAL` finding.

`SecurityErrorCode` contains only `INVALID_INPUT`, `INVALID_ROLE`, `INACTIVE_AGENT`,
`INVALID_PERMISSION`, `INVALID_TOOLS`, `INVALID_SCOPE`, `SCANNER_FAILURE`, `PROVIDER_FAILURE`,
`INVALID_ANALYSIS`, `TIMEOUT`, and `INTERNAL_FAILURE`. `SecurityError` retains only the code and a
constant safe message.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 1 command. Expected: all tests pass without warnings.

- [ ] **Step 5: Commit Task 1**

```bash
git add core/security tests/security
git commit -m "feat(security): define bounded security contracts"
```

---

### Task 2: Fail-closed Security authority and scope validation

**Files:**
- Create: `core/security/validation.py`
- Create: `tests/security/test_validation.py`
- Modify: `core/security/__init__.py`
- Modify: `tests/security/factories.py`

**Interfaces:**
- Consumes: `SecurityRequest`, `AgentProfile`, `Permission`, `AgentStatus`, and
  `ToolExecutionContext`.
- Produces: `ValidatedSecurityRequest`, `validate_security_request(request: SecurityRequest)`, and
  `validate_security_profile_authority(profile: AgentProfile)`.

- [ ] **Step 1: Write failing preflight tests**

Cover valid read-only authority and rejection for wrong role, inactive profile, autonomy outside
zero or one, identity reuse, profile/context mismatch, task/project/correlation mismatch, missing
filesystem read, write permissions, shell/tests/network/database/deployment permissions, write or
command tools, Git-read tools without `git.read`, unapproved QA, mismatched QA tests, duplicate
affected paths, and forged Pydantic subclasses.

```python
def test_validation_rejects_shell_and_command_authority() -> None:
    request = security_request(
        profile=security_profile(
            permission_ids=frozenset({"filesystem.read", "shell.execute"}),
            tool_ids=frozenset({"read_file", "run_command_profile"}),
        )
    )
    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)
    assert raised.value.code is SecurityErrorCode.INVALID_PERMISSION


def test_validation_requires_four_independent_role_identities() -> None:
    request = security_request(security_id=QA_SLUG)
    with pytest.raises(SecurityError) as raised:
        validate_security_request(request)
    assert raised.value.code is SecurityErrorCode.INVALID_SCOPE
```

- [ ] **Step 2: Run validation tests and observe RED**

```bash
.venv/bin/pytest tests/security/test_validation.py -q
```

Expected: import failure for `core.security.validation`.

- [ ] **Step 3: Implement canonical least-privilege validation**

Define exact authority sets:

```python
SECURITY_TOOL_IDS = frozenset(
    {"read_file", "list_files", "search_text", "git_status", "git_diff"}
)
_READ_TOOLS = frozenset({"read_file", "list_files", "search_text"})
_GIT_TOOLS = frozenset({"git_status", "git_diff"})
_REQUIRED_PERMISSIONS = frozenset({Permission.FILESYSTEM_READ})
_ALLOWED_PERMISSIONS = _REQUIRED_PERMISSIONS | frozenset({Permission.GIT_READ})
_ACTIVE_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})
```

`ValidatedSecurityRequest` is a frozen slotted dataclass with canonical `request` and permissions.
Reconstruct the request and profile before authority checks. Require role exactly `Security`, active
status, autonomy `0` or `1`, at least one filesystem read tool, optional Git tools only with
`git.read`, exact profile/context declarations, four distinct identities, same task/project/
correlation across request and execution context, successful canonical QA evidence, and exact test
equality. Clear raw exception frames and expose only stable `SecurityError` values.

- [ ] **Step 4: Verify GREEN with contract regressions**

```bash
.venv/bin/pytest tests/security/test_types.py tests/security/test_errors.py \
  tests/security/test_validation.py -q
```

- [ ] **Step 5: Commit Task 2**

```bash
git add core/security tests/security
git commit -m "feat(security): enforce independent security authority"
```

---

### Task 3: Bounded secret redaction and scanner boundary

**Files:**
- Create: `core/security/ports.py`
- Create: `core/security/redaction.py`
- Create: `tests/security/test_redaction.py`
- Create: `tests/security/test_ports.py`
- Modify: `core/security/__init__.py`
- Modify: `tests/security/factories.py`

**Interfaces:**
- Consumes: `ValidatedSecurityRequest` and bounded source values.
- Produces: `SecurityScannerPort`,
  `sanitize_security_source(request: SecurityRequest) -> SanitizedSecuritySource`, and stable local
  evidence source `synapseos.secret-patterns`.

```python
@runtime_checkable
class SecurityScannerPort(Protocol):
    async def scan(self, request: ValidatedSecurityRequest) -> SecurityScannerReport: ...
```

- [ ] **Step 1: Write failing redaction tests**

Test redaction of PEM private-key blocks and explicit quoted assignments for `api_key`, `apikey`,
`client_secret`, `password`, `secret`, and `token`. Assert detected values are absent from sanitized
diff/source, findings, repr, validation errors, and tracebacks. Assert stable path/line metadata,
confirmed `CRITICAL` private-key findings, confirmed `HIGH` credential-assignment findings, bounded
match count, UTF-8 aggregate limits, deterministic ordering, no false confirmation for key names
without values, and no I/O or persistent history.

```python
def test_private_key_is_redacted_without_retaining_its_value() -> None:
    secret = "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----"
    request = security_request(
        affected_files=(security_source_file("config/key.pem", secret),)
    )
    sanitized = sanitize_security_source(request)
    assert secret not in sanitized.files[0].content
    assert "private-material" not in repr(sanitized)
    assert sanitized.findings[0].severity is SecuritySeverity.CRITICAL
    assert sanitized.findings[0].confirmation is SecurityConfirmation.CONFIRMED
```

- [ ] **Step 2: Write failing scanner-protocol contract tests**

Create a recording fake implementing `SecurityScannerPort`. Assert the protocol accepts one
validated request, returns one canonical metadata-only report, and exposes no close/retry API.

- [ ] **Step 3: Run Task 3 tests and observe RED**

```bash
.venv/bin/pytest tests/security/test_redaction.py tests/security/test_ports.py -q
```

- [ ] **Step 4: Implement the narrow local filter and scanner protocol**

Use precompiled bounded regular expressions. Replace values with `[REDACTED_SECRET]`; never copy a
matched value into any object. Generate evidence IDs from path-or-diff location and line number,
not from content. Stop after sixty-four findings and set `complete=False` when the input or match
budget prevents full coverage. Keep the implementation pure and synchronous; it opens no file,
starts no process, makes no network call, and writes no log.

The scanner port returns only a canonical `SecurityScannerReport`. Do not create Semgrep, Trivy,
ZAP, shell, subprocess, HTTP, or MCP implementations.

- [ ] **Step 5: Verify GREEN and run source-safety regressions**

```bash
.venv/bin/pytest tests/security/test_redaction.py tests/security/test_ports.py \
  tests/tools/test_filesystem_tools.py tests/llm -q
```

- [ ] **Step 6: Commit Task 3**

```bash
git add core/security tests/security
git commit -m "feat(security): redact secrets before analysis"
```

---

### Task 4: One-shot bounded Security analysis

**Files:**
- Create: `core/security/analysis.py`
- Create: `tests/security/test_analysis.py`
- Create: `tests/security/test_safety.py`
- Modify: `core/security/__init__.py`
- Modify: `tests/security/factories.py`

**Interfaces:**
- Consumes: `LLMProvider`, canonical `SecurityRequest`, `SanitizedSecuritySource`, and
  `SecurityScannerReport`.
- Produces: `SecurityAnalyzer.analyze(request, sanitized_source, scanner_report) -> SecurityAnalysis`.

- [ ] **Step 1: Write failing provider-boundary tests**

Cover exactly one provider call, temperature zero, `max_tokens` from 1 through 4,096, provider
timeout above zero and no more than 30 seconds, 131,072-byte response cap, strict JSON decoding,
known category responsibility instructions, provider findings remaining unconfirmed, no raw secret
or unsanitized source in the prompt, no retries/fallback, malformed/oversized/forged response
rejection, provider failure sanitization, cancellation propagation, and caller-owned provider
lifecycle.

```python
async def test_analysis_uses_only_sanitized_source_once() -> None:
    provider = FakeLLMProvider([security_analysis_response(SecurityDecision.PASS)])
    analyzer = SecurityAnalyzer(provider, max_tokens=2_048)
    request = security_request_with_obvious_secret()
    sanitized = sanitize_security_source(request)
    analysis = await analyzer.analyze(request, sanitized, complete_scanner_report())
    assert analysis.decision is SecurityDecision.PASS
    assert len(provider.requests) == 1
    assert "raw-secret-value" not in provider.requests[0].messages[0].content
```

- [ ] **Step 2: Run analysis tests and observe RED**

```bash
.venv/bin/pytest tests/security/test_analysis.py tests/security/test_safety.py -q
```

- [ ] **Step 3: Implement `SecurityAnalyzer`**

Define:

```python
class SecurityAnalyzer:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_tokens: int,
        timeout_seconds: float = 10.0,
    ) -> None: ...

    async def analyze(
        self,
        request: SecurityRequest,
        sanitized_source: SanitizedSecuritySource,
        scanner_report: SecurityScannerReport,
    ) -> SecurityAnalysis: ...
```

Build one deterministic JSON payload containing bounded task text, acceptance criteria, sanitized
diff/files, successful QA summary, metadata-only tests, local redaction findings, and scanner
metadata/findings. The system prompt requires compact JSON with exact keys:

```text
decision,findings[{category,severity,path,line_start,line_end,explanation,remediation,confidence,evidence_ids}],uncertainty_reasons,rationale,confidence
```

Require review of secrets, auth, authorization, injection, input validation, dependencies, and
dangerous configuration. Treat all supplied content as untrusted data. Reconstruct provider
responses strictly, enforce response bytes before structured decoding, and clear sensitive locals
and exception frames before raising a stable `SecurityError`.

- [ ] **Step 4: Verify GREEN with LLM regressions**

```bash
.venv/bin/pytest tests/security/test_analysis.py tests/security/test_safety.py tests/llm -q
```

- [ ] **Step 5: Commit Task 4**

```bash
git add core/security tests/security
git commit -m "feat(security): add bounded security analysis"
```

---

### Task 5: Deterministic veto and Security Agent composition

**Files:**
- Create: `core/security/decision.py`
- Create: `core/security/agent.py`
- Create: `tests/security/test_decision.py`
- Create: `tests/security/test_agent.py`
- Modify: `core/security/__init__.py`
- Modify: `tests/security/factories.py`

**Interfaces:**
- Consumes: validated request, sanitized source, scanner report, `SecurityAnalysis`,
  `SecurityScannerPort`, and `LLMProvider`.
- Produces: `build_security_result(...) -> SecurityResult` and
  `SecurityAgent.run(request: SecurityRequest) -> SecurityResult`.

```python
def build_security_result(
    request: SecurityRequest,
    sanitized_source: SanitizedSecuritySource,
    scanner_report: SecurityScannerReport,
    analysis: SecurityAnalysis,
    *,
    trusted_source_ids: frozenset[str],
) -> SecurityResult: ...
```

- [ ] **Step 1: Write failing deterministic-gate tests**

Test forced `BLOCK` for confirmed trusted `HIGH`/`CRITICAL` local or scanner findings even when the
provider proposes `PASS`. Test `WARN` for suspected findings, confirmed `INFO`/`LOW`/`MEDIUM`,
provider `WARN`, provider-only `BLOCK`, uncertainty, low confidence below `0.80`, incomplete or
truncated sanitization/scanner evidence, failed/truncated QA tests, unknown evidence references,
and untrusted scanner source IDs. Test `PASS` only for complete successful evidence, zero findings,
provider `PASS`, no uncertainty, exact scope, and confidence at least `0.80`.

```python
def test_confirmed_trusted_high_finding_overrides_provider_pass() -> None:
    result = build_security_result(
        security_request(),
        clean_sanitized_source(),
        scanner_report(findings=(confirmed_scanner_finding(SecuritySeverity.HIGH),)),
        passing_security_analysis(),
        trusted_source_ids=frozenset({"scanner.local"}),
    )
    assert result.decision is SecurityDecision.BLOCK


def test_unconfirmed_provider_block_becomes_warn_not_pass() -> None:
    result = build_security_result(
        security_request(),
        clean_sanitized_source(),
        complete_scanner_report(),
        blocking_analysis_with_suspected_finding(),
        trusted_source_ids=frozenset({"scanner.local"}),
    )
    assert result.decision is SecurityDecision.WARN
```

- [ ] **Step 2: Write failing agent-composition tests**

Assert validation occurs before scanner/provider work; sanitization occurs before provider
construction; scanner is called once; provider is called once after scanner; scanner exception and
malformed report become `SCANNER_FAILURE`; provider exception becomes `PROVIDER_FAILURE`; global
timeout becomes `TIMEOUT`; cancellation stops before any later call; no retry/history exists; and
scanner/provider objects are never closed.

- [ ] **Step 3: Run Task 5 tests and observe RED**

```bash
.venv/bin/pytest tests/security/test_decision.py tests/security/test_agent.py -q
```

- [ ] **Step 4: Implement the gate and `SecurityAgent`**

Implement:

```python
class SecurityAgent:
    __slots__ = ("_analyzer", "_scanner", "_trusted_source_ids")

    def __init__(
        self,
        provider: LLMProvider,
        scanner: SecurityScannerPort,
        *,
        trusted_source_ids: frozenset[str],
        max_tokens: int = 2_048,
        provider_timeout_seconds: float = 10.0,
    ) -> None: ...

    async def run(self, request: SecurityRequest) -> SecurityResult: ...
```

Validate before entering the global timeout. Inside one `asyncio.timeout` block, sanitize locally,
call the scanner once, strictly reconstruct its metadata-only report, call the analyzer once, and
apply the gate. Trusted confirmation requires the fixed local source ID
`synapseos.secret-patterns` or a scanner suite ID in the immutable constructor allowlist. The
caller cannot remove trust from the built-in local redactor, and provider evidence is always
suspected. Redact exact source echoes and obvious secret markers from public rationale/findings.
Re-raise cancellation immediately and sanitize every other failure.

- [ ] **Step 5: Verify GREEN and all Security unit tests**

```bash
.venv/bin/pytest tests/security -q
```

- [ ] **Step 6: Commit Task 5**

```bash
git add core/security tests/security
git commit -m "feat(security): compose deterministic security veto"
```

---

### Task 6: Persistent Security workflow contracts and preflight

**Files:**
- Create: `core/workflows/security_types.py`
- Create: `core/workflows/security_errors.py`
- Create: `core/workflows/security_ports.py`
- Create: `core/workflows/security_validation.py`
- Create: `tests/workflows/security_factories.py`
- Create: `tests/workflows/test_security_types.py`
- Create: `tests/workflows/test_security_validation.py`
- Modify: `core/workflows/__init__.py`

**Interfaces:**
- Consumes: persistent `Task` and four `Agent` rows, `SecurityRequest`, `SecurityResult`, and
  `validate_security_request`.
- Produces: `SecurityWorkflowOutcome`, `SecurityWorkflowRequest`, `SecurityWorkflowResult`,
  `SecurityWorkflowErrorCode`, `SecurityWorkflowError`, `SecurityRunner`,
  `ValidatedSecurityWorkflowScope`, and `validate_security_workflow_request`.

```python
class SecurityWorkflowOutcome(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class SecurityWorkflowRequest(_ImmutableSecurityWorkflowModel):
    task_id: UUID
    developer_agent_id: UUID
    reviewer_agent_id: UUID
    qa_agent_id: UUID
    security_agent_id: UUID
    security_request: SecurityRequest
    correlation_id: UUID


class SecurityWorkflowResult(_ImmutableSecurityWorkflowModel):
    task_status: TaskStatus
    outcome: SecurityWorkflowOutcome
    security_result: SecurityResult
    correlation_id: UUID


class SecurityRunner(Protocol):
    async def run(self, request: SecurityRequest) -> SecurityResult: ...
```

- [ ] **Step 1: Write failing workflow contract tests**

Cover immutable nested reconstruction, four distinct persistent agent UUIDs, exact nested task and
correlation scope, and truthful terminal pairs:

```python
VALID_SECURITY_TERMINALS = {
    (TaskStatus.COMPLETED, SecurityWorkflowOutcome.PASS, SecurityDecision.PASS),
    (
        TaskStatus.WAITING_HUMAN,
        SecurityWorkflowOutcome.WARN,
        SecurityDecision.WARN,
    ),
    (
        TaskStatus.CHANGES_REQUESTED,
        SecurityWorkflowOutcome.BLOCK,
        SecurityDecision.BLOCK,
    ),
}
```

- [ ] **Step 2: Write failing real-PostgreSQL preflight tests**

Use Alembic-backed fixtures. Cover missing task/agents, non-`WAITING_SECURITY` state, wrong roles,
inactive agents, reused UUIDs/slugs, Developer assignment mismatch, nested slug/profile mismatch,
task/project/correlation/workspace mismatch, failed QA evidence, invalid Security authority, and a
valid canonical scope. Assert every failure changes no state, commits no audit event, and invokes no
Security runner.

```python
def test_security_preflight_requires_waiting_security(db_session: Session) -> None:
    request = persisted_security_workflow_request(
        db_session,
        task_status=TaskStatus.WAITING_QA,
    )
    with pytest.raises(SecurityWorkflowError) as raised:
        validate_security_workflow_request(db_session, request)
    assert raised.value.code is SecurityWorkflowErrorCode.INVALID_STATE
```

- [ ] **Step 3: Run Task 6 tests and observe RED**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows/test_security_types.py \
  tests/workflows/test_security_validation.py -q
```

- [ ] **Step 4: Implement workflow types, errors, port, and persistent preflight**

Strictly canonicalize nested values. Load and row-lock the task, then load Developer, Reviewer, QA,
and Security agents. Require exact active roles, four distinct identities, preserved Developer
assignment, task state `WAITING_SECURITY`, exact task/project/context/correlation scope, successful
QA evidence, and valid Security authority. Persistent preflight authenticates database identities
and managed-workspace scope; it does not claim PostgreSQL can authenticate caller-supplied source
bytes. Return a frozen slotted `ValidatedSecurityWorkflowScope`. Never commit, invoke Security, or
close the caller-owned session during validation.

- [ ] **Step 5: Verify GREEN with QA workflow regressions**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows/test_security_types.py \
  tests/workflows/test_security_validation.py tests/workflows/test_qa_validation.py -q
```

- [ ] **Step 6: Commit Task 6**

```bash
git add core/workflows tests/workflows
git commit -m "feat(workflow): validate persistent security scope"
```

---

### Task 7: Append-only Security checkpoints and orchestration

**Files:**
- Create: `core/workflows/security_audit.py`
- Create: `core/workflows/security_orchestrator.py`
- Create: `tests/workflows/test_security_audit.py`
- Create: `tests/workflows/test_security_orchestrator.py`
- Create: `tests/workflows/test_security_safety.py`
- Modify: `core/workflows/__init__.py`
- Modify: `tests/workflows/security_factories.py`

**Interfaces:**
- Consumes: `ValidatedSecurityWorkflowScope`, `SecurityRunner`, `TaskStateMachine`, and append-only
  `AuditEvent`.
- Produces: `SecurityWorkflowOrchestrator.run(request) -> SecurityWorkflowResult` and committed
  Security checkpoint helpers.

- [ ] **Step 1: Write failing checkpoint and audit tests**

Cover row-locked `SECURITY_STARTED`, duplicate/stale start rejection, atomic completion plus state
transition, one correlation ID, rollback, append-only behavior, and an exact audit allowlist. Assert
audit data contains counts and stable identifiers only and excludes source, diff, paths,
explanations, remediations, evidence text, secret values, QA details, prompts, responses, scanner
output, provider metadata, and raw exceptions.

- [ ] **Step 2: Write failing orchestration tests**

Cover one Security call and exact transitions:

```python
SECURITY_TRANSITIONS = {
    SecurityDecision.PASS: TaskStatus.COMPLETED,
    SecurityDecision.WARN: TaskStatus.WAITING_HUMAN,
    SecurityDecision.BLOCK: TaskStatus.CHANGES_REQUESTED,
}
```

Also cover global deadline from `security_request.timeout_seconds`, malformed collaborator result,
scanner/provider/runtime failure to `WAITING_HUMAN` through `SECURITY_ESCALATED`, cancellation with
no later checkpoint, concurrent human transition winning, database failure with no retry, no
automatic Developer/Git/deployment call, and caller-owned session/runner.

- [ ] **Step 3: Run Task 7 tests and observe RED**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows/test_security_audit.py \
  tests/workflows/test_security_orchestrator.py \
  tests/workflows/test_security_safety.py -q
```

- [ ] **Step 4: Implement durable Security checkpoints**

Define:

```python
class SecurityEventType(StrEnum):
    SECURITY_STARTED = "SECURITY_STARTED"
    SECURITY_COMPLETED = "SECURITY_COMPLETED"
    SECURITY_ESCALATED = "SECURITY_ESCALATED"
```

`commit_security_started_checkpoint` requires `WAITING_SECURITY`, rejects an existing unmatched
start, stages only Security agent ID and bounded input counts, and commits. Completion reacquires
the task row lock, verifies expected state and Developer assignment, calls
`TaskStateMachine.transition`, stages `SECURITY_COMPLETED`, and commits atomically. Audit only
decision, confidence, finding counts by severity, confirmed blocker count, scanner suite ID,
scanner completion/truncation flags, and correlation scope.

- [ ] **Step 5: Implement `SecurityWorkflowOrchestrator`**

```python
class SecurityWorkflowOrchestrator:
    __slots__ = ("_security", "_session")

    def __init__(self, session: Session, security: SecurityRunner) -> None: ...

    async def run(self, request: SecurityWorkflowRequest) -> SecurityWorkflowResult: ...
```

Derive one monotonic deadline, validate persistent scope, commit `SECURITY_STARTED`, invoke Security
once, reconstruct the result strictly, verify correlation and result scope, and commit exactly one
permitted transition. Operational failures use a bounded recovery deadline to attempt
`WAITING_HUMAN` only while the task remains `WAITING_SECURITY`. Cancellation re-raises immediately
without an escalation checkpoint.

- [ ] **Step 6: Verify GREEN with Phase 16 and 17 workflow regressions**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/workflows -q
```

- [ ] **Step 7: Commit Task 7**

```bash
git add core/workflows tests/workflows
git commit -m "feat(workflow): orchestrate audited security gate"
```

---

### Task 8: PostgreSQL read authority and concrete integration

**Files:**
- Create: `infrastructure/permissions/security_policy.py`
- Create: `tests/database/test_security_permission_policy.py`
- Create: `tests/security/integration_fixtures.py`
- Create: `tests/security/test_integration.py`
- Create: `tests/workflows/test_security_integration.py`
- Modify: `infrastructure/permissions/__init__.py`

**Interfaces:**
- Consumes: persisted `Agent`, `AgentPermission`, `AgentRun`, `Task`, `PolicyRequest`, concrete
  `SecurityAgent`, fake scanner/provider ports, and `SecurityWorkflowOrchestrator`.
- Produces: `SQLAlchemySecurityPermissionPolicy` and real-PostgreSQL acceptance evidence for the
  complete Phase 18 data path.

- [ ] **Step 1: Write failing deny-by-default policy tests**

Define the only accepted tool capabilities:

```python
SECURITY_READ_CAPABILITIES = {
    "read_file": (ToolRiskLevel.LOW, frozenset({Permission.FILESYSTEM_READ})),
    "list_files": (ToolRiskLevel.LOW, frozenset({Permission.FILESYSTEM_READ})),
    "search_text": (ToolRiskLevel.LOW, frozenset({Permission.FILESYSTEM_READ})),
    "git_status": (ToolRiskLevel.LOW, frozenset({Permission.GIT_READ})),
    "git_diff": (ToolRiskLevel.LOW, frozenset({Permission.GIT_READ})),
}
```

Test allow only for an active persistent Security run on the exact `WAITING_SECURITY` task with a
distinct active Developer assignee and exact active project/global grants. Test deny for unknown
tool, wrong risk, extra permission, missing/revoked/expired grant, inactive/wrong-role agent,
autonomy above one, wrong task/project/run, non-running run, wrong task state, self-review,
write/shell/deployment requests, and production access. Test database failures are sanitized and
the session remains caller-owned.

- [ ] **Step 2: Run policy tests and observe RED**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest \
  tests/database/test_security_permission_policy.py -q
```

- [ ] **Step 3: Implement `SQLAlchemySecurityPermissionPolicy`**

Canonicalize `PolicyRequest`, require timezone-aware evaluation time, match one exact capability
entry, load the active Security run/task/Developer scope, query only required live grants, and
return existing `PermissionDecision` values. Deny every capability not listed. Convert SQLAlchemy
failures to the existing sanitized `PermissionPolicyError`. Do not commit, roll back, close the
session, or mutate grants.

- [ ] **Step 4: Write failing concrete Security and workflow integration tests**

Against the Alembic-built PostgreSQL schema, persist Developer, Reviewer, QA, and Security agents,
a `WAITING_SECURITY` task assigned to Developer, active grants, and a Security run. Compose a real
`SecurityAgent` with `FakeLLMProvider` and a bounded recording scanner. Verify:

- clean evidence produces one scanner call, one provider call, `PASS`, one start event, one
  completion event, one status event, and `COMPLETED`;
- trusted confirmed high evidence produces `BLOCK` and `CHANGES_REQUESTED`;
- suspected evidence produces `WARN` and `WAITING_HUMAN`;
- scanner/provider failure produces `SECURITY_ESCALATED` and no duplicated work;
- all persisted data is metadata-only and append-only.

- [ ] **Step 5: Run integration tests and verify GREEN**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/security/test_integration.py \
  tests/workflows/test_security_integration.py \
  tests/database/test_security_permission_policy.py -q
```

- [ ] **Step 6: Run Phase 18 and regression suites**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/security tests/workflows \
  tests/database/test_security_permission_policy.py -q
```

- [ ] **Step 7: Commit Task 8**

```bash
git add infrastructure/permissions tests/database tests/security tests/workflows
git commit -m "test(security): verify concrete security workflow"
```

---

### Task 9: Documentation, checklist, and final acceptance

**Files:**
- Create: `docs/security-agent.md`
- Modify: `README.md:51-56,215-221,251-253,273-274`
- Modify: `AGENTS.md:10-42,65-71,119-125`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md:1260-1305`
- Modify: `docs/superpowers/plans/2026-09-01-phase-18-security-agent.md`

**Interfaces:**
- Consumes: verified Phase 18 behavior and command evidence.
- Produces: truthful operating documentation and only genuinely completed Phase 18 checkboxes.

- [ ] **Step 1: Document exact Phase 18 behavior**

Document request/result contracts, source bounds, local redaction limits, scanner port, provider
bounds, trusted confirmation, deterministic gate, read-only authority, state transitions, audit
allowlist, error behavior, lifecycle ownership, example composition, and explicit exclusions.
Update repository status and focused test commands without claiming external scanners or Phase 19.

- [ ] **Step 2: Run complete verification before checking boxes**

```bash
TEST_POSTGRES_PORT=55432 make test
make lint
make typecheck
.venv/bin/ruff format --check .
git diff --check origin/main...HEAD
```

Inspect the complete diff for secret literals, absolute paths, raw source/output persistence,
provider payload persistence, arbitrary provider metadata, retries, duplicate calls, resource
closure, accidental Phase 19 work, and AI co-author trailers. Run Docker/API health only when
Docker is available and report unavailable evidence honestly.

- [ ] **Step 3: Update only verified Phase 18 checkboxes**

Mark the seven responsibility boxes and three decision boxes only after tests prove them:

- security review;
- secrets;
- auth/authz;
- injections;
- input validation;
- dependencies;
- dangerous configuration;
- `PASS`;
- `WARN`;
- `BLOCK`.

Do not modify Phase 19 or later checkboxes.

- [ ] **Step 4: Re-run final verification after documentation changes**

```bash
TEST_POSTGRES_PORT=55432 make test
make lint
make typecheck
.venv/bin/ruff format --check .
git diff --check origin/main...HEAD
```

- [ ] **Step 5: Commit verified documentation**

```bash
git add README.md AGENTS.md SYNAPSEOS_DEVELOPMENT_CHECKLIST.md docs/security-agent.md \
  docs/superpowers/plans/2026-09-01-phase-18-security-agent.md
git commit -m "docs(security): complete Phase 18 delivery"
```

- [ ] **Step 6: Finish the branch**

Run independent scoped code and security reviews, convert every accepted finding into a failing
regression test before fixing it, repeat the full acceptance gate, push
`phase-18/security-agent`, and open a pull request targeting `main`. The PR description must state
exact test counts, list any unverified Docker evidence, and explicitly confirm that Phase 19 is not
implemented.
