"""Bounded JSONL export for future offline training workflows."""

from __future__ import annotations

import json

from core.security.redaction import contains_obvious_secret
from core.training_dataset.pipeline import _contains_obvious_pii
from core.training_dataset.types import TrainingDataset, TrainingUsage

_MAX_EXPORT_BYTES = 16 * 1024 * 1024


class DatasetExportTooLargeError(RuntimeError):
    """The bounded dataset exceeds the exporter output limit."""


class UnsafeDatasetError(RuntimeError):
    """A record failed the exporter's final safety and authorization gate."""


class DatasetExporter:
    """Serialize validated records without persistence or provider calls."""

    def to_jsonl(self, dataset: TrainingDataset) -> str:
        if type(dataset) is not TrainingDataset:
            raise ValueError("dataset must be canonical")
        canonical = TrainingDataset.model_validate(
            dataset.model_dump(mode="python", warnings=False),
            strict=True,
        )
        _require_safe_dataset(canonical)
        records: list[str] = []
        for example in canonical.examples:
            records.append(
                _record(
                    record_type="training_example",
                    dataset=canonical,
                    payload=example.model_dump(mode="json", warnings=False),
                )
            )
        for pair in canonical.preference_pairs:
            records.append(
                _record(
                    record_type="preference_pair",
                    dataset=canonical,
                    payload=pair.model_dump(mode="json", warnings=False),
                )
            )
        exported = "\n".join(records)
        if len(exported.encode("utf-8")) > _MAX_EXPORT_BYTES:
            raise DatasetExportTooLargeError("dataset export exceeds the configured limit")
        return exported


def _require_safe_dataset(dataset: TrainingDataset) -> None:
    for example in dataset.examples:
        if (
            not example.consent.authorized
            or TrainingUsage.FINE_TUNING not in example.consent.allowed_uses
            or _contains_unsafe_content(
                (
                    example.prompt_context,
                    example.decision,
                    *example.alternatives,
                    example.output,
                    example.review,
                    example.user_feedback,
                )
            )
        ):
            raise UnsafeDatasetError("dataset contains unsafe content")
    for pair in dataset.preference_pairs:
        if (
            not pair.consent.authorized
            or TrainingUsage.PREFERENCE_LEARNING not in pair.consent.allowed_uses
            or _contains_unsafe_content((pair.prompt_context, pair.preferred, pair.rejected))
        ):
            raise UnsafeDatasetError("dataset contains unsafe content")


def _contains_unsafe_content(values: tuple[str | None, ...]) -> bool:
    return any(
        contains_obvious_secret(value) or _contains_obvious_pii(value)
        for value in values
        if value is not None
    )


def _record(
    *,
    record_type: str,
    dataset: TrainingDataset,
    payload: dict[str, object],
) -> str:
    return json.dumps(
        {
            "record_type": record_type,
            "dataset_name": dataset.name,
            "dataset_version": dataset.version,
            **payload,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
