"""Pure bounded secret redaction before external Security analysis."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from core.security.types import (
    SanitizedSecuritySource,
    SecurityConfirmation,
    SecurityEvidenceReference,
    SecurityRequest,
    SecurityScannerFinding,
    SecuritySeverity,
    SecuritySourceFile,
)

REDACTED_SECRET = "[REDACTED_SECRET]"
SECRET_PATTERN_SOURCE_ID = "synapseos.secret-patterns"
MAX_SECRET_FINDINGS = 64
_DIFF_PATH = "diff.patch"
_PRIVATE_KEY_LABEL = r"(?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY"
_CREDENTIAL_KEYS = r"(?:api_key|apikey|client_secret|password|secret|token)"
_DOUBLE_QUOTED_CREDENTIAL_VALUE = r'(?:\\[^\r\n]|[^"\\\r\n])+'
_SINGLE_QUOTED_CREDENTIAL_VALUE = r"(?:\\[^\r\n]|[^'\\\r\n])+"
_SECRET_PATTERN = re.compile(
    rf"(?P<private_key>"
    rf"-----BEGIN (?P<private_key_label>{_PRIVATE_KEY_LABEL})-----"
    rf".*?"
    rf"-----END (?P=private_key_label)-----"
    rf")"
    rf"|"
    rf"(?P<credential>"
    rf"(?P<credential_prefix>"
    rf"(?<![A-Za-z0-9_])"
    rf"(?:\"{_CREDENTIAL_KEYS}\"|'{_CREDENTIAL_KEYS}'|{_CREDENTIAL_KEYS})"
    rf"(?![A-Za-z0-9_])"
    rf"\s*(?:=|:)\s*"
    rf")"
    rf'(?:"(?P<credential_double_value>{_DOUBLE_QUOTED_CREDENTIAL_VALUE})"'
    rf"|'(?P<credential_single_value>{_SINGLE_QUOTED_CREDENTIAL_VALUE})')"
    rf")",
    flags=re.IGNORECASE | re.DOTALL,
)


@dataclass(slots=True)
class _RedactionState:
    findings: list[SecurityScannerFinding] = field(default_factory=list)
    complete: bool = True
    match_count: int = 0


def sanitize_security_source(request: SecurityRequest) -> SanitizedSecuritySource:
    """Return bounded sanitized source without retaining or persisting matched values."""
    if type(request) is not SecurityRequest:
        raise TypeError("security request must be canonical") from None

    state = _RedactionState()
    sanitized_diff = _sanitize_text(
        request.diff,
        location=_DIFF_PATH,
        state=state,
    )
    sanitized_files = tuple(
        SecuritySourceFile(
            path=item.path,
            content=_sanitize_text(item.content, location=item.path, state=state),
        )
        for item in request.affected_files
    )
    return SanitizedSecuritySource(
        diff=sanitized_diff,
        files=sanitized_files,
        findings=tuple(state.findings),
        complete=state.complete,
    )


def _sanitize_text(text: str, *, location: str, state: _RedactionState) -> str:
    original_byte_count = len(text.encode("utf-8"))
    original_character_count = len(text)

    def replace(match: re.Match[str]) -> str:
        state.match_count += 1
        if len(state.findings) < MAX_SECRET_FINDINGS:
            state.findings.append(
                _finding_for_match(
                    match,
                    location=location,
                    ordinal=state.match_count,
                )
            )
        else:
            state.complete = False

        if match.group("private_key") is not None:
            return REDACTED_SECRET
        prefix = match.group("credential_prefix")
        quote = '"' if match.group("credential_double_value") is not None else "'"
        return f"{prefix}{quote}{REDACTED_SECRET}{quote}"

    sanitized = _SECRET_PATTERN.sub(replace, text)
    bounded, truncated = _bound_text(
        sanitized,
        max_bytes=original_byte_count,
        max_characters=original_character_count,
    )
    if truncated:
        state.complete = False
    return bounded


def _finding_for_match(
    match: re.Match[str],
    *,
    location: str,
    ordinal: int,
) -> SecurityScannerFinding:
    line_start = match.string.count("\n", 0, match.start()) + 1
    line_end = line_start + match.group(0).count("\n")
    is_private_key = match.group("private_key") is not None
    category = "secret.private-key" if is_private_key else "secret.credential-assignment"
    severity = SecuritySeverity.CRITICAL if is_private_key else SecuritySeverity.HIGH
    explanation = (
        "A private-key block was present in the supplied source."
        if is_private_key
        else "A quoted credential assignment was present in the supplied source."
    )
    remediation = (
        "Remove the private key, rotate it, and load it through an approved secret store."
        if is_private_key
        else "Remove the credential, rotate it, and load it through an approved secret store."
    )
    evidence_id = _evidence_id(
        location=location,
        line=line_start,
        category=category,
        ordinal=ordinal,
    )
    return SecurityScannerFinding(
        category=category,
        severity=severity,
        path=location,
        line_start=line_start,
        line_end=line_end,
        explanation=explanation,
        remediation=remediation,
        confidence=1.0,
        evidence=(
            SecurityEvidenceReference(
                source_id=SECRET_PATTERN_SOURCE_ID,
                evidence_id=evidence_id,
            ),
        ),
        confirmation=SecurityConfirmation.CONFIRMED,
    )


def _evidence_id(*, location: str, line: int, category: str, ordinal: int) -> str:
    location_digest = hashlib.blake2s(location.encode("utf-8"), digest_size=6).hexdigest()
    category_slug = category.replace(".", "-")
    return f"{category_slug}:{location_digest}:line-{line}:match-{ordinal}"


def _bound_text(text: str, *, max_bytes: int, max_characters: int) -> tuple[str, bool]:
    bounded = text[:max_characters]
    encoded = bounded.encode("utf-8")
    if len(encoded) > max_bytes:
        bounded = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return bounded, bounded != text
