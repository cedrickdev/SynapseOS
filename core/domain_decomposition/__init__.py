"""Phase 27 business-domain decomposition contracts and composition."""

from core.domain_decomposition.decomposer import DomainDecomposer
from core.domain_decomposition.errors import (
    DomainDecompositionError,
    DomainDecompositionErrorCode,
)
from core.domain_decomposition.types import (
    DomainDecomposition,
    DomainDecompositionRequest,
    DomainWorkstream,
    WorkstreamScope,
)

__all__ = [
    "DomainDecomposer",
    "DomainDecomposition",
    "DomainDecompositionError",
    "DomainDecompositionErrorCode",
    "DomainDecompositionRequest",
    "DomainWorkstream",
    "WorkstreamScope",
]
