"""Pane lifecycle result types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaneExitState:
    """Exit state observed for a dead pane."""

    dead: bool
    status: int | None = None
