"""Public Phase 18 Security Agent contracts."""

from core.security.agent import SecurityAgent
from core.security.analysis import SecurityAnalyzer
from core.security.decision import build_security_result
from core.security.errors import SecurityError, SecurityErrorCode
from core.security.ports import SecurityScannerPort
from core.security.redaction import (
    MAX_SECRET_FINDINGS,
    REDACTED_SECRET,
    SECRET_PATTERN_SOURCE_ID,
    sanitize_security_source,
)
from core.security.scanners import (
    DependencyAuditScanner,
    ScannerCommandResult,
    ScannerOutputError,
    SecretScanner,
    SecurityScanner,
    SemgrepScanner,
    TrivyScanner,
)
from core.security.types import (
    SanitizedSecuritySource,
    SecurityAnalysis,
    SecurityAnalysisFinding,
    SecurityConfirmation,
    SecurityDecision,
    SecurityEvidenceReference,
    SecurityFinding,
    SecurityRequest,
    SecurityResult,
    SecurityScannerFinding,
    SecurityScannerReport,
    SecurityScannerSummary,
    SecuritySeverity,
    SecuritySourceFile,
)
from core.security.validation import (
    SECURITY_TOOL_IDS,
    ValidatedSecurityRequest,
    validate_security_profile_authority,
    validate_security_request,
)

__all__ = [
    "SecurityAgent",
    "build_security_result",
    "SanitizedSecuritySource",
    "SecurityAnalysis",
    "SecurityAnalysisFinding",
    "SecurityAnalyzer",
    "SecurityConfirmation",
    "SecurityDecision",
    "SecurityError",
    "SecurityErrorCode",
    "SecurityEvidenceReference",
    "SecurityFinding",
    "SecurityRequest",
    "SecurityResult",
    "SecurityScannerFinding",
    "SecurityScannerPort",
    "SecurityScanner",
    "ScannerCommandResult",
    "ScannerOutputError",
    "SemgrepScanner",
    "TrivyScanner",
    "SecretScanner",
    "DependencyAuditScanner",
    "SecurityScannerReport",
    "SecurityScannerSummary",
    "SecuritySeverity",
    "SecuritySourceFile",
    "MAX_SECRET_FINDINGS",
    "REDACTED_SECRET",
    "SECRET_PATTERN_SOURCE_ID",
    "SECURITY_TOOL_IDS",
    "ValidatedSecurityRequest",
    "validate_security_profile_authority",
    "validate_security_request",
    "sanitize_security_source",
]
