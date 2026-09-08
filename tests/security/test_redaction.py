"""Behavioral tests for bounded local Security source redaction."""

from __future__ import annotations

import builtins
import traceback
from pathlib import Path

import pytest

import core.security.redaction as security_redaction
from core.security import SecurityConfirmation, SecuritySeverity
from core.security.redaction import REDACTED_SECRET, sanitize_security_source
from tests.security.factories import security_request, source_file


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('token = "metadata-secret"', True),
        (
            "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----",
            True,
        ),
        ("api_key = os.environ['API_KEY']", False),
    ],
)
def test_obvious_secret_predicate_reuses_all_task_3_detector_shapes(
    text: str,
    expected: bool,
) -> None:
    """Catch predicates narrowed away from Task 3 credential or private-key detection."""
    assert security_redaction.contains_obvious_secret(text) is expected


def test_private_key_is_redacted_without_retaining_its_value(tmp_path: Path) -> None:
    secret = "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----"
    request = security_request(
        tmp_path,
        affected_files=(source_file(path="config/key.pem", content=secret),),
    )

    sanitized = sanitize_security_source(request)

    assert sanitized.files[0].content == REDACTED_SECRET
    assert secret not in repr(sanitized)
    assert "private-material" not in repr(sanitized)
    assert sanitized.complete is True
    assert len(sanitized.findings) == 1
    finding = sanitized.findings[0]
    assert finding.path == "config/key.pem"
    assert (finding.line_start, finding.line_end) == (1, 3)
    assert finding.severity is SecuritySeverity.CRITICAL
    assert finding.confirmation is SecurityConfirmation.CONFIRMED
    assert finding.evidence[0].source_id == "synapseos.secret-patterns"


@pytest.mark.parametrize(
    ("key", "separator", "quote"),
    [
        ("api_key", "=", '"'),
        ("apikey", ":", "'"),
        ("client_secret", "=", '"'),
        ("password", ":", "'"),
        ("secret", "=", '"'),
        ("token", ":", "'"),
    ],
)
def test_quoted_credential_assignments_are_redacted_and_confirmed(
    tmp_path: Path,
    key: str,
    separator: str,
    quote: str,
) -> None:
    secret = f"sensitive-{key}-value"
    content = f"before = 1\n{key} {separator} {quote}{secret}{quote}\nafter = 2\n"
    request = security_request(
        tmp_path,
        affected_files=(source_file(path="config/settings.py", content=content),),
    )

    sanitized = sanitize_security_source(request)

    assert secret not in sanitized.files[0].content
    assert secret not in repr(sanitized)
    assert REDACTED_SECRET in sanitized.files[0].content
    assert len(sanitized.findings) == 1
    finding = sanitized.findings[0]
    assert finding.path == "config/settings.py"
    assert (finding.line_start, finding.line_end) == (2, 2)
    assert finding.severity is SecuritySeverity.HIGH
    assert finding.confirmation is SecurityConfirmation.CONFIRMED


def test_unquoted_credential_assignment_is_redacted_before_provider_use(
    tmp_path: Path,
) -> None:
    """Cover common dotenv and shell-style credentials without quotes."""
    secret = "sk-live-unquoted-redaction-marker"
    request = security_request(
        tmp_path,
        affected_files=(source_file(path="config/runtime.env", content=f"API_KEY={secret}\n"),),
    )

    sanitized = sanitize_security_source(request)

    assert secret not in sanitized.files[0].content
    assert sanitized.files[0].content == "API_KEY=[REDACTED_SECRET]\n"
    assert sanitized.findings[0].category == "secret.credential-assignment"


@pytest.mark.parametrize(
    ("quote", "secret"),
    [
        ('"', "prefix'opposite-quote-secret-suffix"),
        ("'", 'prefix"opposite-quote-secret-suffix'),
    ],
)
def test_quoted_credential_values_with_opposite_quotes_are_fully_redacted(
    tmp_path: Path,
    quote: str,
    secret: str,
) -> None:
    content = f"token = {quote}{secret}{quote}"
    request = security_request(
        tmp_path,
        affected_files=(source_file(content=content),),
    )

    sanitized = sanitize_security_source(request)

    assert sanitized.files[0].content == f"token = {quote}{REDACTED_SECRET}{quote}"
    assert secret not in repr(sanitized)
    assert "opposite-quote-secret-suffix" not in repr(sanitized)
    assert len(sanitized.findings) == 1


@pytest.mark.parametrize(
    ("quote", "secret"),
    [
        ('"', r"prefix\"escaped-quote-secret-suffix"),
        ("'", r"prefix\'escaped-quote-secret-suffix"),
    ],
)
def test_quoted_credential_values_with_escaped_active_quotes_are_fully_redacted(
    tmp_path: Path,
    quote: str,
    secret: str,
) -> None:
    content = f"token = {quote}{secret}{quote}"
    request = security_request(
        tmp_path,
        affected_files=(source_file(content=content),),
    )

    sanitized = sanitize_security_source(request)

    assert sanitized.files[0].content == f"token = {quote}{REDACTED_SECRET}{quote}"
    assert secret not in repr(sanitized)
    assert "escaped-quote-secret-suffix" not in repr(sanitized)
    assert len(sanitized.findings) == 1


def test_encrypted_private_key_is_redacted_as_confirmed_critical_evidence(
    tmp_path: Path,
) -> None:
    secret = (
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\n"
        "encrypted-private-material\n"
        "-----END ENCRYPTED PRIVATE KEY-----"
    )
    request = security_request(
        tmp_path,
        affected_files=(source_file(path="config/key.pem", content=secret),),
    )

    sanitized = sanitize_security_source(request)

    assert sanitized.files[0].content == REDACTED_SECRET
    assert secret not in repr(sanitized)
    assert "encrypted-private-material" not in repr(sanitized)
    assert len(sanitized.findings) == 1
    finding = sanitized.findings[0]
    assert finding.severity is SecuritySeverity.CRITICAL
    assert finding.confirmation is SecurityConfirmation.CONFIRMED


def test_redaction_covers_diff_and_files_in_deterministic_location_order(tmp_path: Path) -> None:
    request = security_request(
        tmp_path,
        diff='+token = "diff-secret"\n+safe = True\n',
        affected_files=(
            source_file(
                path="src/first.py",
                content='safe = True\npassword = "first-secret"\n',
            ),
            source_file(
                path="src/second.py",
                content=(
                    "-----BEGIN RSA PRIVATE KEY-----\n"
                    "second-secret\n"
                    "-----END RSA PRIVATE KEY-----\n"
                ),
            ),
        ),
    )

    first = sanitize_security_source(request)
    second = sanitize_security_source(request)

    assert first == second
    assert "diff-secret" not in first.diff
    assert "first-secret" not in first.files[0].content
    assert "second-secret" not in first.files[1].content
    assert tuple((item.path, item.line_start) for item in first.findings) == (
        ("diff.patch", 1),
        ("src/first.py", 2),
        ("src/second.py", 1),
    )
    evidence_ids = tuple(item.evidence[0].evidence_id for item in first.findings)
    assert len(set(evidence_ids)) == 3


@pytest.mark.parametrize(
    "content",
    [
        "token\n",
        "api_key = os.environ['API_KEY']\n",
        'password = ""\n',
        "client_secret: null\n",
        "def rotate_secret() -> None:\n    pass\n",
    ],
)
def test_secret_key_names_without_quoted_values_are_not_confirmed(
    tmp_path: Path,
    content: str,
) -> None:
    request = security_request(
        tmp_path,
        affected_files=(source_file(content=content),),
    )

    sanitized = sanitize_security_source(request)

    assert sanitized.files[0].content == content
    assert sanitized.findings == ()
    assert sanitized.complete is True


def test_findings_are_bounded_while_every_detected_value_is_redacted(tmp_path: Path) -> None:
    secrets = tuple(f"credential-value-longer-than-mask-{index:03d}" for index in range(70))
    content = "\n".join(f'token = "{secret}"' for secret in secrets)
    request = security_request(
        tmp_path,
        affected_files=(source_file(content=content),),
    )

    sanitized = sanitize_security_source(request)

    assert len(sanitized.findings) == 64
    assert sanitized.complete is False
    assert all(secret not in sanitized.files[0].content for secret in secrets)
    assert sanitized.files[0].content.count(REDACTED_SECRET) == 70


def test_utf8_output_stays_within_original_aggregate_budget(tmp_path: Path) -> None:
    content = ('token = "é"\n' * 1_000).rstrip()
    request = security_request(
        tmp_path,
        affected_files=(source_file(content=content),),
    )

    sanitized = sanitize_security_source(request)

    assert len(sanitized.files[0].content.encode("utf-8")) <= len(content.encode("utf-8"))
    assert sanitized.complete is False
    assert "é" not in sanitized.files[0].content


def test_redaction_is_pure_and_does_not_retain_prior_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("redaction must not perform file I/O")

    monkeypatch.setattr(builtins, "open", fail_open)
    first_secret = "first-sensitive-value"
    first = sanitize_security_source(
        security_request(
            tmp_path,
            affected_files=(source_file(content=f'token = "{first_secret}"'),),
        )
    )
    second = sanitize_security_source(
        security_request(
            tmp_path,
            affected_files=(source_file(content='token = "second-sensitive-value"'),),
        )
    )

    assert first_secret not in repr(first)
    assert first_secret not in repr(second)


def test_invalid_input_error_and_traceback_do_not_include_source_value() -> None:
    secret = "traceback-sensitive-value"

    with pytest.raises(TypeError) as captured:
        sanitize_security_source({"diff": secret})  # type: ignore[arg-type]

    rendered = "".join(
        traceback.format_exception(
            type(captured.value),
            captured.value,
            captured.value.__traceback__,
        )
    )
    assert secret not in str(captured.value)
    assert secret not in rendered
