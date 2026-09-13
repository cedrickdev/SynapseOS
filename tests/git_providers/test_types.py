from __future__ import annotations

import importlib
import inspect
from typing import get_type_hints
from uuid import UUID

import pytest
from pydantic import ValidationError


def test_repository_coordinates_are_strict_immutable_and_canonical() -> None:
    try:
        module = importlib.import_module("core.git_providers.types")
    except ModuleNotFoundError:
        pytest.fail("remote Git contract module is missing")

    coordinates = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")

    assert coordinates.full_name == "neocraft/synapse-os"
    with pytest.raises(ValidationError):
        coordinates.owner = "other"
    for values in (
        {"owner": "NeoCraft", "repository": "synapse-os"},
        {"owner": "-neocraft", "repository": "synapse-os"},
        {"owner": "neocraft", "repository": ".git"},
        {"owner": "neocraft", "repository": "synapse/os"},
        {"owner": "neocraft", "repository": "synapse-os", "token": "secret"},
    ):
        with pytest.raises(ValueError):
            module.RepositoryCoordinates(**values)


def test_remote_branch_requires_canonical_name_and_exact_sha() -> None:
    module = importlib.import_module("core.git_providers.types")

    branch = module.RemoteBranch(name="feature/github-provider", sha="a" * 40)

    assert branch.name == "feature/github-provider"
    assert branch.sha == "a" * 40
    for values in (
        {"name": "main..backup", "sha": "a" * 40},
        {"name": "feature//github", "sha": "a" * 40},
        {"name": "feature/github.lock", "sha": "a" * 40},
        {"name": "feature/github", "sha": "A" * 40},
        {"name": "feature/github", "sha": "a" * 39},
    ):
        with pytest.raises(ValueError):
            module.RemoteBranch(**values)


def test_remote_branch_rejects_git_ref_control_syntax() -> None:
    module = importlib.import_module("core.git_providers.types")

    for name in ("feature~one", "feature^one", "feature:one", "feature?one", "feature*one"):
        with pytest.raises(ValueError):
            module.RemoteBranch(name=name, sha="a" * 40)


def test_remote_file_change_rejects_unsafe_repository_paths() -> None:
    module = importlib.import_module("core.git_providers.types")

    change = module.RemoteFileChange(path="core/git_providers/types.py", content="safe")

    assert change.path == "core/git_providers/types.py"
    for path in ("/etc/passwd", "../secret", "core\\secret", ".git/config", "a/./b"):
        with pytest.raises(ValueError):
            module.RemoteFileChange(path=path, content="safe")


def test_remote_file_change_bounds_utf8_payload_bytes() -> None:
    module = importlib.import_module("core.git_providers.types")

    accepted = module.RemoteFileChange(path="payload.txt", content="a" * 1_048_576)

    assert len(accepted.content.encode("utf-8")) == 1_048_576
    with pytest.raises(ValueError):
        module.RemoteFileChange(path="payload.txt", content="é" * 524_289)


def test_branch_creation_is_sha_bound_and_rejects_protected_targets() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")

    request = module.CreateRemoteBranchRequest(
        repository=repository,
        branch="feature/github-provider",
        base_sha="b" * 40,
    )

    assert request.base_sha == "b" * 40
    for branch in ("main", "production"):
        with pytest.raises(ValueError):
            module.CreateRemoteBranchRequest(
                repository=repository,
                branch=branch,
                base_sha="b" * 40,
            )


def test_remote_commit_copies_changes_and_rejects_duplicate_paths() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")
    changes = [module.RemoteFileChange(path="one.txt", content="one")]

    request = module.RemoteCommitRequest(
        repository=repository,
        branch="feature/github-provider",
        expected_head_sha="c" * 40,
        message="feat: add remote provider contracts",
        changes=changes,
    )
    changes.append(module.RemoteFileChange(path="two.txt", content="two"))

    assert tuple(item.path for item in request.changes) == ("one.txt",)
    with pytest.raises(ValueError):
        module.RemoteCommitRequest(
            repository=repository,
            branch="feature/github-provider",
            expected_head_sha="c" * 40,
            message="feat: duplicate",
            changes=(
                module.RemoteFileChange(path="same.txt", content="one"),
                module.RemoteFileChange(path="same.txt", content="two"),
            ),
        )


def test_remote_merge_request_binds_internal_gate_and_remote_head_inputs() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")
    pull_request_id = UUID("11111111-1111-1111-1111-111111111111")
    task_id = UUID("22222222-2222-2222-2222-222222222222")
    git_evidence_event_id = UUID("33333333-3333-3333-3333-333333333333")

    request = module.RemoteMergeRequest(
        repository=repository,
        number=41,
        expected_head_sha="d" * 40,
        pull_request_id=pull_request_id,
        expected_task_id=task_id,
        git_evidence_event_id=git_evidence_event_id,
        method=module.RemoteMergeMethod.SQUASH,
    )

    assert request.expected_head_sha == "d" * 40
    assert request.pull_request_id == pull_request_id
    with pytest.raises(ValueError):
        module.RemoteMergeRequest(
            repository=repository,
            number=0,
            expected_head_sha="d" * 40,
            pull_request_id=pull_request_id,
            expected_task_id=task_id,
            git_evidence_event_id=git_evidence_event_id,
            method=module.RemoteMergeMethod.SQUASH,
        )


def test_remote_pull_request_read_uses_validated_immutable_input() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")

    request = module.RemotePullRequestRequest(repository=repository, number=41)

    assert request.number == 41
    with pytest.raises(ValidationError):
        request.number = 42
    for number in (0, -1, True):
        with pytest.raises(ValueError):
            module.RemotePullRequestRequest(repository=repository, number=number)


def test_remote_check_read_uses_validated_immutable_sha_input() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")

    request = module.RemoteChecksRequest(repository=repository, head_sha="a" * 40)

    assert request.head_sha == "a" * 40
    for head_sha in ("A" * 40, "a" * 39, "main"):
        with pytest.raises(ValueError):
            module.RemoteChecksRequest(repository=repository, head_sha=head_sha)


def test_remote_operation_options_reject_non_finite_or_non_positive_timeouts() -> None:
    module = importlib.import_module("core.git_providers.types")

    options = module.RemoteOperationOptions(timeout_seconds=30.0)

    assert options.timeout_seconds == 30.0
    with pytest.raises(ValidationError):
        options.timeout_seconds = 20.0
    for timeout in (0.0, -1.0, float("inf"), float("-inf"), float("nan"), 300.1):
        with pytest.raises(ValueError):
            module.RemoteOperationOptions(timeout_seconds=timeout)


def test_pull_request_text_payloads_are_trimmed_and_bounded() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")

    request = module.CreateRemotePullRequestRequest(
        repository=repository,
        head_branch="feature/github-provider",
        base_branch="main",
        title="Add GitHub provider contracts",
        body="Bounded provider-neutral contracts.",
    )

    assert request.title == "Add GitHub provider contracts"
    for title, body in (("x" * 257, "safe"), ("safe", "x" * 65_537), (" padded ", "safe")):
        with pytest.raises(ValueError):
            module.CreateRemotePullRequestRequest(
                repository=repository,
                head_branch="feature/github-provider",
                base_branch="main",
                title=title,
                body=body,
            )


def test_remote_git_errors_expose_only_bounded_sanitized_context() -> None:
    try:
        errors = importlib.import_module("core.git_providers.errors")
    except ModuleNotFoundError:
        pytest.fail("remote Git error contracts are missing")

    error = errors.RemoteGitError(
        errors.RemoteGitErrorCode.STALE_STATE,
        "Remote repository state changed.",
        status_code=409,
    )

    assert str(error) == "Remote repository state changed."
    assert error.code is errors.RemoteGitErrorCode.STALE_STATE
    assert error.status_code == 409
    assert not hasattr(error, "body")
    assert not hasattr(error, "token")
    with pytest.raises(ValueError):
        errors.RemoteGitError(errors.RemoteGitErrorCode.PROVIDER_FAILED, "x" * 256)
    with pytest.raises(ValueError):
        errors.RemoteGitError(errors.RemoteGitErrorCode.PROVIDER_FAILED, "unsafe\nmessage")


def test_remote_git_error_rejects_credential_bearing_messages_without_echoing_them() -> None:
    errors = importlib.import_module("core.git_providers.errors")

    unsafe_messages = (
        "GitHub rejected ghp_0123456789abcdefghijklmnopqrstuvwxyz.",
        "Authorization: Bearer highly-sensitive-value",
        "password=highly-sensitive-value",
        "secret: highly-sensitive-value",
        "token = highly-sensitive-value",
        "token=" + "x" * 300,
    )
    for unsafe_message in unsafe_messages:
        with pytest.raises(ValueError) as captured:
            errors.RemoteGitError(errors.RemoteGitErrorCode.PROVIDER_FAILED, unsafe_message)
        assert unsafe_message not in str(captured.value)


def test_remote_results_are_immutable_and_allowlisted() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")
    branch = module.RemoteBranch(name="feature/github-provider", sha="e" * 40)

    metadata = module.RemoteRepositoryMetadata(
        repository=repository,
        default_branch="main",
        private=True,
        archived=False,
    )
    commit = module.RemoteCommitResult(
        repository=repository,
        branch=branch,
        previous_sha="d" * 40,
        commit_sha="e" * 40,
        tree_sha="f" * 40,
    )

    assert metadata.repository.full_name == "neocraft/synapse-os"
    assert commit.branch.sha == commit.commit_sha
    with pytest.raises(ValidationError):
        metadata.archived = True
    with pytest.raises(ValueError):
        module.RemoteCommitResult(
            repository=repository,
            branch=branch,
            previous_sha="d" * 40,
            commit_sha="a" * 40,
            tree_sha="f" * 40,
        )


def test_pull_request_review_check_and_merge_results_are_sha_bound() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")

    pull_request = module.RemotePullRequest(
        repository=repository,
        number=41,
        state=module.RemotePullRequestState.OPEN,
        title="Add GitHub provider contracts",
        head_branch="feature/github-provider",
        base_branch="main",
        head_sha="a" * 40,
        mergeable=True,
    )
    review = module.RemoteReview(
        review_id=7,
        reviewer="independent-reviewer",
        state=module.RemoteReviewState.APPROVED,
        commit_sha="a" * 40,
    )
    check = module.RemoteCheck(
        name="backend",
        status=module.RemoteCheckStatus.COMPLETED,
        conclusion=module.RemoteCheckConclusion.SUCCESS,
        head_sha="a" * 40,
    )
    result = module.RemoteMergeResult(
        repository=repository,
        number=41,
        merged=True,
        sha="b" * 40,
        message="Pull request merged.",
    )

    assert (pull_request.head_sha, review.commit_sha, check.head_sha) == ("a" * 40,) * 3
    assert result.sha == "b" * 40
    with pytest.raises(ValueError):
        module.RemoteMergeResult(
            repository=repository,
            number=41,
            merged=True,
            sha=None,
            message="Pull request merged.",
        )


def test_remote_audit_event_is_bounded_immutable_and_secret_free_by_shape() -> None:
    module = importlib.import_module("core.git_providers.types")
    repository = module.RepositoryCoordinates(owner="neocraft", repository="synapse-os")

    event = module.RemoteGitAuditEvent(
        actor_id="agent:developer",
        project_id=UUID("11111111-1111-1111-1111-111111111111"),
        task_id=UUID("22222222-2222-2222-2222-222222222222"),
        agent_run_id=UUID("33333333-3333-3333-3333-333333333333"),
        correlation_id=UUID("44444444-4444-4444-4444-444444444444"),
        repository=repository,
        operation=module.RemoteGitOperation.CREATE_BRANCH,
        outcome=module.RemoteGitAuditOutcome.STARTED,
        detail="Creating a SHA-bound branch.",
    )

    assert "token" not in event.model_dump()
    with pytest.raises(ValidationError):
        event.detail = "changed"
    with pytest.raises(ValueError):
        module.RemoteGitAuditEvent(**{**event.model_dump(), "detail": "x" * 256, "token": "secret"})


def test_remote_audit_event_redacts_credential_bearing_detail() -> None:
    module = importlib.import_module("core.git_providers.types")
    base = {
        "actor_id": "agent:developer",
        "project_id": UUID("11111111-1111-1111-1111-111111111111"),
        "task_id": UUID("22222222-2222-2222-2222-222222222222"),
        "agent_run_id": UUID("33333333-3333-3333-3333-333333333333"),
        "correlation_id": UUID("44444444-4444-4444-4444-444444444444"),
        "repository": module.RepositoryCoordinates(owner="neocraft", repository="synapse-os"),
        "operation": module.RemoteGitOperation.CREATE_BRANCH,
        "outcome": module.RemoteGitAuditOutcome.FAILED,
    }
    unsafe_details = (
        "GitHub rejected github_pat_highly_sensitive_value",
        "Authorization: Bearer highly-sensitive-value",
        "Bearer highly-sensitive-value",
        "password=highly-sensitive-value",
        "secret: highly-sensitive-value",
        "token = highly-sensitive-value",
    )

    for unsafe_detail in unsafe_details:
        event = module.RemoteGitAuditEvent(**base, detail=unsafe_detail)
        serialized = str(event.model_dump())
        assert event.detail == "Sensitive detail redacted."
        assert unsafe_detail not in serialized


def test_remote_ports_accept_structurally_compatible_adapters() -> None:
    try:
        ports = importlib.import_module("core.git_providers.ports")
    except ModuleNotFoundError:
        pytest.fail("remote Git provider ports are missing")

    class TokenProvider:
        async def get_token(self, *, options: object) -> str:
            del options
            return "in-memory-only"

    class AuditSink:
        def record(self, event: object) -> None:
            del event

    class MergeGate:
        def evaluate(self, **kwargs: object) -> object:
            return kwargs

    class Provider:
        async def get_repository(self, *args: object, **kwargs: object) -> object:
            return (args, kwargs)

        async def create_branch(self, *args: object, **kwargs: object) -> object:
            return (args, kwargs)

        async def commit_and_push(self, *args: object, **kwargs: object) -> object:
            return (args, kwargs)

        async def create_pull_request(self, *args: object, **kwargs: object) -> object:
            return (args, kwargs)

        async def get_pull_request(self, *args: object, **kwargs: object) -> object:
            return (args, kwargs)

        async def list_reviews(self, *args: object, **kwargs: object) -> object:
            return (args, kwargs)

        async def list_checks(self, *args: object, **kwargs: object) -> object:
            return (args, kwargs)

        async def merge_pull_request(self, *args: object, **kwargs: object) -> object:
            return (args, kwargs)

    assert isinstance(TokenProvider(), ports.GitHubTokenProvider)
    assert isinstance(AuditSink(), ports.RemoteGitAuditSink)
    assert isinstance(MergeGate(), ports.RemoteMergeGate)
    assert isinstance(Provider(), ports.RemoteGitProvider)


def test_remote_ports_accept_only_validated_request_and_options_models() -> None:
    ports = importlib.import_module("core.git_providers.ports")
    types = importlib.import_module("core.git_providers.types")

    for method_name in (
        "get_repository",
        "create_branch",
        "commit_and_push",
        "create_pull_request",
        "get_pull_request",
        "list_reviews",
        "list_checks",
        "merge_pull_request",
    ):
        method = getattr(ports.RemoteGitProvider, method_name)
        signature = inspect.signature(method)
        hints = get_type_hints(method)
        assert "timeout_seconds" not in signature.parameters
        assert hints["options"] is types.RemoteOperationOptions

    for method_name in ("get_pull_request", "list_reviews"):
        method = getattr(ports.RemoteGitProvider, method_name)
        assert get_type_hints(method)["request"] is types.RemotePullRequestRequest
        assert "number" not in inspect.signature(method).parameters

    check_method = ports.RemoteGitProvider.list_checks
    assert get_type_hints(check_method)["request"] is types.RemoteChecksRequest
    assert "head_sha" not in inspect.signature(check_method).parameters

    token_method = ports.GitHubTokenProvider.get_token
    assert get_type_hints(token_method)["options"] is types.RemoteOperationOptions
    assert "timeout_seconds" not in inspect.signature(token_method).parameters


def test_package_exposes_the_public_remote_contract_surface() -> None:
    package = importlib.import_module("core.git_providers")

    assert package.RepositoryCoordinates.__name__ == "RepositoryCoordinates"
    assert package.RemoteGitProvider.__name__ == "RemoteGitProvider"
    assert package.GitHubTokenProvider.__name__ == "GitHubTokenProvider"
    assert package.RemoteGitAuditSink.__name__ == "RemoteGitAuditSink"
    assert package.RemoteMergeGate.__name__ == "RemoteMergeGate"
    assert package.RemoteGitError.__name__ == "RemoteGitError"
    assert package.RemoteOperationOptions.__name__ == "RemoteOperationOptions"
    assert package.RemotePullRequestRequest.__name__ == "RemotePullRequestRequest"
    assert package.RemoteChecksRequest.__name__ == "RemoteChecksRequest"
