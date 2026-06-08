"""Pane output streams backed by control mode."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .control import ControlExit, ControlModeClient, ControlOutput
from .expectations import Duration
from .snapshots import PaneSnapshot

if TYPE_CHECKING:
    from .server import Pane


@dataclass(frozen=True)
class PaneOutputChunk:
    """One raw output chunk emitted by a pane."""

    pane_id: str
    data: bytes


class PaneOutputStream:
    """Synchronous raw pane output stream."""

    def __init__(self, pane: "Pane") -> None:
        self._pane = pane
        self._pane_id = pane.id()
        self._control = ControlModeClient(pane.server.control_mode())
        self._control.send_command(f"attach-session -t {pane.target}")

    def __enter__(self) -> "PaneOutputStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying control-mode client."""

        self._control.close()

    def next(self, timeout: Duration | None = None) -> PaneOutputChunk:
        """Return the next raw output chunk for this pane."""

        while True:
            event = self._control.read_event(timeout=timeout)
            if isinstance(event, ControlExit):
                raise EOFError("control-mode stream exited")
            if isinstance(event, ControlOutput):
                if self._pane_id is None or event.pane_id == self._pane_id:
                    return PaneOutputChunk(event.pane_id, event.data)


class PaneLineStream:
    """Line stream built from raw pane output bytes."""

    def __init__(self, output: PaneOutputStream) -> None:
        self._output = output
        self._buffer = bytearray()
        self._pending: deque[str] = deque()

    def __enter__(self) -> "PaneLineStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying output stream."""

        self._output.close()

    def next(self, timeout: Duration | None = None) -> str:
        """Return the next complete decoded line."""

        while True:
            if self._pending:
                return self._pending.popleft()
            chunk = self._output.next(timeout=timeout)
            self._feed(chunk.data)

    def _feed(self, data: bytes) -> None:
        self._buffer.extend(data)
        while True:
            try:
                index = self._buffer.index(0x0A)
            except ValueError:
                return
            line = bytes(self._buffer[:index])
            del self._buffer[: index + 1]
            if line.endswith(b"\r"):
                line = line[:-1]
            self._pending.append(line.decode("utf-8", errors="replace"))


class PaneRenderStream:
    """Snapshot stream triggered by pane output."""

    def __init__(self, pane: "Pane") -> None:
        self._pane = pane
        self._output = PaneOutputStream(pane)

    def __enter__(self) -> "PaneRenderStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying output stream."""

        self._output.close()

    def next(self, timeout: Duration | None = None) -> PaneSnapshot:
        """Wait for output and return a fresh pane snapshot."""

        self._output.next(timeout=timeout)
        return self._pane.snapshot()
