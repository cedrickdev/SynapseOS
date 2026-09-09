"""Phase 20 pull-request infrastructure adapters."""

from infrastructure.pull_requests.gate import SQLAlchemyMergeGate

__all__ = ["SQLAlchemyMergeGate"]
