"""Provider-neutral OIDC authentication contracts."""

from core.auth.types import OIDCClaims, OIDCConfiguration, OIDCVerificationError

__all__ = ["OIDCClaims", "OIDCConfiguration", "OIDCVerificationError"]
