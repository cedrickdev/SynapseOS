"""Tests for the Phase 44 validated training dataset pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.training_dataset import (
    DatasetExporter,
    ExperienceProvenance,
    TrainingConsent,
    TrainingDatasetPipeline,
    TrainingUsage,
    UnsafeDatasetError,
    ValidatedExperience,
)


def _experience(**changes: object) -> ValidatedExperience:
    values: dict[str, object] = {
        "experience_id": "experience-001",
        "validated": True,
        "prompt_context": "Implement a bounded health endpoint.",
        "decision": "Use a dependency-free liveness route.",
        "alternatives": ("Use a database readiness check.",),
        "result": "The endpoint returns a stable OK response.",
        "review": "Approved after tests passed.",
        "user_feedback": "The endpoint meets the acceptance criteria.",
        "corrected_answer": "The endpoint returns OK without querying dependencies.",
        "reward_candidate": Decimal("0.9000"),
        "provenance": ExperienceProvenance(
            project_id="project-001",
            source_event_ids=("event-001", "event-002"),
            validated_by="reviewer-agent",
            validation_event_id="event-validation-001",
            collected_at=datetime(2026, 9, 13, tzinfo=UTC),
        ),
        "consent": TrainingConsent(
            authorized=True,
            data_owner_id="owner-001",
            consent_reference="consent-001",
            allowed_uses=(TrainingUsage.FINE_TUNING, TrainingUsage.PREFERENCE_LEARNING),
        ),
    }
    values.update(changes)
    return ValidatedExperience.model_validate(values)


def test_pipeline_builds_versioned_examples_and_preference_pairs() -> None:
    dataset = TrainingDatasetPipeline().build(
        name="engineering-v1",
        version="1.0.0",
        experiences=(_experience(),),
    )

    assert dataset.name == "engineering-v1"
    assert dataset.version == "1.0.0"
    assert len(dataset.examples) == 1
    assert dataset.examples[0].output == "The endpoint returns a stable OK response."
    assert dataset.examples[0].provenance.validation_event_id == "event-validation-001"
    assert len(dataset.preference_pairs) == 1
    assert dataset.preference_pairs[0].preferred == (
        "The endpoint returns OK without querying dependencies."
    )
    assert dataset.preference_pairs[0].rejected == ("The endpoint returns a stable OK response.")


def test_pipeline_excludes_unvalidated_or_unauthorized_experiences() -> None:
    unvalidated = _experience(experience_id="experience-unvalidated", validated=False)
    unauthorized = _experience(
        experience_id="experience-unauthorized",
        consent=TrainingConsent(
            authorized=False,
            data_owner_id="owner-001",
            consent_reference="consent-denied",
            allowed_uses=(),
        ),
    )

    dataset = TrainingDatasetPipeline().build(
        name="engineering-v1",
        version="1.0.0",
        experiences=(unvalidated, unauthorized),
    )

    assert dataset.examples == ()
    assert dataset.preference_pairs == ()
    assert dataset.excluded_count == 2
    assert dataset.exclusion_reasons == ("NOT_AUTHORIZED", "NOT_VALIDATED")


def test_pipeline_excludes_secret_and_pii_without_leaking_them() -> None:
    secret = _experience(
        experience_id="experience-secret",
        prompt_context='api_key = "super-secret-value"',
    )
    pii = _experience(
        experience_id="experience-pii",
        user_feedback="Contact customer@example.com about this result.",
    )

    dataset = TrainingDatasetPipeline().build(
        name="engineering-v1",
        version="1.0.0",
        experiences=(secret, pii),
    )
    exported = DatasetExporter().to_jsonl(dataset)

    assert dataset.excluded_count == 2
    assert dataset.exclusion_reasons == ("PII_DETECTED", "SECRET_DETECTED")
    assert "super-secret-value" not in exported
    assert "customer@example.com" not in exported


def test_exporter_emits_bounded_jsonl_records_with_usage_metadata() -> None:
    dataset = TrainingDatasetPipeline().build(
        name="engineering-v1",
        version="1.0.0",
        experiences=(_experience(),),
    )

    records = [json.loads(line) for line in DatasetExporter().to_jsonl(dataset).splitlines()]

    assert [record["record_type"] for record in records] == [
        "training_example",
        "preference_pair",
    ]
    assert records[0]["dataset_version"] == "1.0.0"
    assert records[0]["consent"]["consent_reference"] == "consent-001"
    assert "fine_tuning" in records[0]["consent"]["allowed_uses"]


def test_exporter_rejects_unsafe_content_even_if_pipeline_was_bypassed() -> None:
    dataset = TrainingDatasetPipeline().build(
        name="engineering-v1",
        version="1.0.0",
        experiences=(_experience(),),
    )
    unsafe_example = dataset.examples[0].model_copy(
        update={"output": 'password = "must-never-be-exported"'}
    )
    unsafe_dataset = dataset.model_copy(update={"examples": (unsafe_example,)})

    with pytest.raises(UnsafeDatasetError, match="dataset contains unsafe content"):
        DatasetExporter().to_jsonl(unsafe_dataset)


def test_pii_filter_does_not_reject_an_iso_date() -> None:
    experience = _experience(review="Validated on 2026-09-13 after deterministic checks.")

    dataset = TrainingDatasetPipeline().build(
        name="engineering-v1",
        version="1.0.0",
        experiences=(experience,),
    )

    assert len(dataset.examples) == 1
    assert dataset.excluded_count == 0
