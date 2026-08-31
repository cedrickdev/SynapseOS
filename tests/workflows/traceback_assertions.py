"""Assertions for leak-resistant public workflow tracebacks."""

from __future__ import annotations

from types import TracebackType


def assert_workflow_frames_are_scope_free(
    traceback: TracebackType | None,
    *,
    filenames: frozenset[str],
    markers: tuple[str, ...],
) -> None:
    """Reject sensitive workflow objects and their marker-bearing representations."""
    forbidden_locals = frozenset(
        {
            "self",
            "session",
            "request",
            "scope",
            "context",
            "developer_result",
            "reviewer_result",
            "handoff",
            "profile",
            "task",
        }
    )
    while traceback is not None:
        frame = traceback.tb_frame
        if any(frame.f_code.co_filename.endswith(filename) for filename in filenames):
            retained = sorted(
                name
                for name in forbidden_locals.intersection(frame.f_locals)
                if frame.f_locals[name] is not None
            )
            assert retained == [], (frame.f_code.co_name, retained)
            for value in frame.f_locals.values():
                rendered = repr(value)
                assert all(marker not in rendered for marker in markers)
        traceback = traceback.tb_next
