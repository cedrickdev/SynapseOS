"""Idempotent persistence of Trust events from vetted Genome evidence."""

from __future__ import annotations

from sqlalchemy.orm import Session

from infrastructure.database.models import AgentGenomeEvidence, AgentTrustEvent
from infrastructure.database.repositories.agent_trust import AgentTrustRepository
from infrastructure.trust.adapters import TrustEvidenceAdapter


class TrustEvidenceIngestor:
    """Persist only deterministic events derived from immutable trusted evidence."""

    def __init__(self, session: Session) -> None:
        self._repository = AgentTrustRepository(session)

    def ingest(self, evidence: AgentGenomeEvidence) -> AgentTrustEvent | None:
        event = TrustEvidenceAdapter.from_genome_evidence(evidence)
        if event is None:
            return None
        return self._repository.add_event_idempotent(event)
