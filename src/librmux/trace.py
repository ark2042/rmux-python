"""Minimal JSONL tracing."""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from .handles import Pane


class RmuxTraceBuilder:
    """Builder for an in-memory trace session."""

    def __init__(self, *, max_events: int = 100_000) -> None:
        self._max_events = max_events

    def max_events(self, value: int) -> "RmuxTraceBuilder":
        """Set the maximum retained event count."""

        self._max_events = value
        return self

    def start(self) -> "TraceSession":
        """Start tracing."""

        trace = TraceSession(max_events=self._max_events)
        trace._record("trace.start", {})
        return trace


class TraceSession:
    """Active in-memory trace session."""

    def __init__(self, *, max_events: int) -> None:
        self._max_events = max_events
        self._events: deque[dict[str, Any]] = deque()

    def record_action(self, action: str) -> None:
        """Record a free-form action."""

        self._record("action", {"action": action})

    def record_snapshot(self, pane: Pane) -> None:
        """Capture and record a pane snapshot."""

        snapshot = pane.snapshot()
        self._record(
            "snapshot",
            {
                "pane": pane.target,
                "visible_text": snapshot.visible_text,
            },
        )

    def stop(self, directory: str | Path) -> Path:
        """Write `trace.jsonl` into ``directory`` and return its path."""

        self._record("trace.stop", {})
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        output = path / "trace.jsonl"
        output.write_text(
            "".join(json.dumps(event) + "\n" for event in self._events),
            encoding="utf-8",
        )
        return output

    def _record(self, kind: str, payload: dict[str, Any]) -> None:
        if self._max_events <= 0:
            return
        if len(self._events) == self._max_events:
            self._events.popleft()
        self._events.append(
            {
                "timestamp_ms": int(time.time() * 1000),
                "kind": kind,
                "payload": payload,
            }
        )
