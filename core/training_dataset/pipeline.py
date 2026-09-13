"""Fail-closed transformation of validated experiences into training records."""

from __future__ import annotations

import re
from collections.abc import Sequence

from core.security.redaction import contains_obvious_secret
from core.training_dataset.types import (
    DatasetExclusionReason,
    PreferencePair,
    TrainingDataset,
    TrainingExample,
    TrainingUsage,
    ValidatedExperience,
)

_MAX_EXPERIENCES = 1_000
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b", re.IGNORECASE)
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?[0-9][0-9 .()\-]{7,}[0-9](?!\w)")


class TrainingDatasetPipeline:
    """Build future-training artifacts without persisting data or running training."""

    def build(
        self,
        *,
        name: str,
        version: str,
        experiences: Sequence[ValidatedExperience],
    ) -> TrainingDataset:
        if not isinstance(experiences, (list, tuple)) or len(experiences) > _MAX_EXPERIENCES:
            raise ValueError("experiences must be a bounded sequence")
        examples: list[TrainingExample] = []
        pairs: list[PreferencePair] = []
        exclusion_reasons: list[DatasetExclusionReason] = []

        for raw_experience in experiences:
            if type(raw_experience) is not ValidatedExperience:
                raise ValueError("experience must be canonical")
            experience = ValidatedExperience.model_validate(
                raw_experience.model_dump(mode="python", warnings=False),
                strict=True,
            )
            reason = _exclusion_reason(experience)
            if reason is not None:
                exclusion_reasons.append(reason)
                continue

            if TrainingUsage.FINE_TUNING in experience.consent.allowed_uses:
                examples.append(_training_example(experience, version))
            if (
                TrainingUsage.PREFERENCE_LEARNING in experience.consent.allowed_uses
                and experience.corrected_answer is not None
                and experience.corrected_answer != experience.result
            ):
                pairs.append(_preference_pair(experience, version))

        return TrainingDataset(
            name=name,
            version=version,
            examples=tuple(examples),
            preference_pairs=tuple(pairs),
            excluded_count=len(exclusion_reasons),
            exclusion_reasons=tuple(sorted(set(exclusion_reasons))),
        )


def _exclusion_reason(experience: ValidatedExperience) -> DatasetExclusionReason | None:
    if not experience.validated:
        return DatasetExclusionReason.NOT_VALIDATED
    if not experience.consent.authorized or not experience.consent.allowed_uses:
        return DatasetExclusionReason.NOT_AUTHORIZED
    content = _content_fields(experience)
    if any(contains_obvious_secret(value) for value in content):
        return DatasetExclusionReason.SECRET_DETECTED
    if any(_contains_obvious_pii(value) for value in content):
        return DatasetExclusionReason.PII_DETECTED
    return None


def _content_fields(experience: ValidatedExperience) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            experience.prompt_context,
            experience.decision,
            *experience.alternatives,
            experience.result,
            experience.review,
            experience.user_feedback,
            experience.corrected_answer,
        )
        if value is not None
    )


def _contains_obvious_pii(value: str) -> bool:
    if _EMAIL_PATTERN.search(value) is not None:
        return True
    return any(
        10 <= sum(character.isdigit() for character in match.group()) <= 15
        for match in _PHONE_PATTERN.finditer(value)
    )


def _training_example(experience: ValidatedExperience, version: str) -> TrainingExample:
    return TrainingExample(
        example_id=f"{experience.experience_id}:v{version}",
        prompt_context=experience.prompt_context,
        decision=experience.decision,
        alternatives=experience.alternatives,
        output=experience.result,
        review=experience.review,
        user_feedback=experience.user_feedback,
        reward_candidate=experience.reward_candidate,
        provenance=experience.provenance,
        consent=experience.consent,
    )


def _preference_pair(experience: ValidatedExperience, version: str) -> PreferencePair:
    corrected_answer = experience.corrected_answer
    if corrected_answer is None:
        raise RuntimeError("corrected answer is required")
    return PreferencePair(
        pair_id=f"{experience.experience_id}:preference:v{version}",
        prompt_context=experience.prompt_context,
        preferred=corrected_answer,
        rejected=experience.result,
        provenance=experience.provenance,
        consent=experience.consent,
    )
