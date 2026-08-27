"""Shared deterministic doubles for Phase 6 tool tests."""

from __future__ import annotations

import pytest

from tests.tools.fakes import FakeTool


@pytest.fixture
def fake_tool() -> FakeTool:
    """Return a fresh deterministic tool and reset its call count."""
    FakeTool.calls = 0
    return FakeTool()
