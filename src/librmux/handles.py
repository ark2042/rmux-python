"""Session, window, and pane handles."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .expectations import (
    Duration,
    TextExpectation,
    TextMatch,
    duration_seconds,
    row_column,
)
from .lifecycle import PaneExitState
from .locators import TextLocator
from .snapshots import PaneSnapshot
from .streams import PaneLineStream, PaneOutputStream, PaneRenderStream

if TYPE_CHECKING:
    from .server import CommandRun, JsonObject, Rmux


@dataclass(frozen=True)
class Session:
    """A session target backed by an ``Rmux`` client."""

    server: "Rmux"
    name: str

    def list_windows(self) -> list["JsonObject"]:
        """Return windows in this session."""

        return self.server.list_windows(target=self.name)

    def windows(self) -> list["Window"]:
        """Return typed window handles for this session."""

        return [
            Window(self.server, self.name, int(window["window_index"]))
            for window in self.list_windows()
        ]

    def window(self, index: int) -> "Window":
        """Return a window handle by index."""

        return Window(self.server, self.name, index)

    def pane(self, window_index: int = 0, pane_index: int = 0) -> "Pane":
        """Return a pane handle by window and pane index."""

        return self.window(window_index).pane(pane_index)


@dataclass(frozen=True)
class Window:
    """A window target backed by an ``Rmux`` client."""

    server: "Rmux"
    session_name: str
    index: int

    @property
    def target(self) -> str:
        """Return the window target string."""

        return f"{self.session_name}:{self.index}"

    def list_panes(self) -> list["JsonObject"]:
        """Return panes in this window."""

        return self.server.list_panes(target=self.target)

    def panes(self) -> list["Pane"]:
        """Return typed pane handles for this window."""

        panes: list[Pane] = []
        for pane in self.list_panes():
            pane_id = pane.get("pane_id")
            if isinstance(pane_id, str) and pane_id:
                target = pane_id
            else:
                target = f"{self.target}.{int(pane['pane_index'])}"
            panes.append(Pane(self.server, target))
        return panes

    def pane(self, index: int) -> "Pane":
        """Return a pane handle by index."""

        return Pane(self.server, f"{self.target}.{index}")


@dataclass(frozen=True)
class Pane:
    """A pane target backed by an ``Rmux`` client."""

    server: "Rmux"
    target: str

    def send_keys(self, *keys: object) -> "CommandRun":
        """Send key tokens or text to this pane."""

        return self.server.send_keys(self.target, *keys)

    def send_text(self, text: str) -> "CommandRun":
        """Send literal text to this pane."""

        return self.server.send_text(self.target, text)

    def capture(
        self,
        *,
        start: int | str | None = None,
        end: int | str | None = None,
        escape_ansi: bool = False,
        join_wrapped: bool = False,
    ) -> str:
        """Return ``capture-pane -p`` text for this pane."""

        return self.server.capture_pane(
            target=self.target,
            start=start,
            end=end,
            escape_ansi=escape_ansi,
            join_wrapped=join_wrapped,
        )

    def capture_text(
        self,
        *,
        start: int | str | None = None,
        end: int | str | None = None,
        escape_ansi: bool = False,
        join_wrapped: bool = False,
    ) -> str:
        """Return visible text captured from this pane."""

        return self.snapshot(
            start=start,
            end=end,
            escape_ansi=escape_ansi,
            join_wrapped=join_wrapped,
        ).visible_text

    def snapshot(
        self,
        *,
        start: int | str | None = None,
        end: int | str | None = None,
        escape_ansi: bool = False,
        join_wrapped: bool = False,
    ) -> PaneSnapshot:
        """Return a typed snapshot of visible pane text."""

        return PaneSnapshot(
            self.capture(
                start=start,
                end=end,
                escape_ansi=escape_ansi,
                join_wrapped=join_wrapped,
            )
        )

    def get_by_text(self, text: str) -> TextLocator:
        """Return a locator for visible pane text."""

        return TextLocator(self, text)

    def locator(self, text: str) -> TextLocator:
        """Return a text locator for this pane."""

        return self.get_by_text(text)

    def id(self) -> str | None:
        """Return the current pane id, when listed."""

        panes = self.server.list_panes(target=self.target)
        if not panes:
            return None
        pane_id = panes[0].get("pane_id")
        return str(pane_id) if pane_id else None

    def output_stream(self) -> PaneOutputStream:
        """Open a raw output stream for this pane."""

        return PaneOutputStream(self)

    def line_stream(self) -> PaneLineStream:
        """Open a decoded line stream for this pane."""

        return PaneLineStream(self.output_stream())

    def render_stream(self) -> PaneRenderStream:
        """Open a snapshot stream triggered by pane output."""

        return PaneRenderStream(self)

    def wait_for_text(
        self,
        text: str,
        *,
        timeout: Duration = 5.0,
        interval: Duration = 0.05,
    ) -> TextMatch:
        """Wait until captured pane text contains ``text``."""

        return self._wait_for_text(text, exact=False, timeout=timeout, interval=interval)

    def wait_for_exact_text(
        self,
        text: str,
        *,
        timeout: Duration = 5.0,
        interval: Duration = 0.05,
    ) -> TextMatch:
        """Wait until captured pane text equals ``text`` after trimming trailing newlines."""

        return self._wait_for_text(text, exact=True, timeout=timeout, interval=interval)

    def expect_visible_text(self) -> TextExpectation:
        """Create a text expectation for this pane."""

        return TextExpectation(self)

    def wait_for_exit(
        self,
        *,
        timeout: Duration = 5.0,
        interval: Duration = 0.05,
    ) -> PaneExitState:
        """Wait until this pane is marked dead."""

        timeout_seconds = duration_seconds(timeout)
        interval_seconds = duration_seconds(interval)
        deadline = time.monotonic() + timeout_seconds
        while True:
            state = self._exit_state()
            if state.dead:
                return state
            if time.monotonic() >= deadline:
                raise TimeoutError(f"pane did not exit before timeout: {self.target}")
            time.sleep(interval_seconds)

    def _wait_for_text(
        self,
        text: str,
        *,
        exact: bool,
        timeout: Duration,
        interval: Duration,
    ) -> TextMatch:
        timeout_seconds = duration_seconds(timeout)
        interval_seconds = duration_seconds(interval)
        deadline = time.monotonic() + timeout_seconds
        while True:
            captured = self.capture_text()
            if exact:
                if captured.rstrip("\n") == text:
                    index = captured.find(text)
                    if index < 0:
                        index = 0
                    row, column = row_column(captured, index)
                    return TextMatch(text=text, row=row, column=column)
            else:
                index = captured.find(text)
                if index >= 0:
                    row, column = row_column(captured, index)
                    return TextMatch(text=text, row=row, column=column)
            if time.monotonic() >= deadline:
                raise AssertionError(f"text not found before timeout: {text!r}")
            time.sleep(interval_seconds)

    def _exit_state(self) -> PaneExitState:
        run = self.server.cmd(
            "display-message",
            "-p",
            "-t",
            self.target,
            "#{pane_dead}:#{pane_dead_status}",
        )
        if run.returncode != 0:
            return PaneExitState(dead=True, status=None)
        dead, _, status = run.stdout.strip().partition(":")
        if dead not in {"1", "true"}:
            return PaneExitState(dead=False, status=None)
        try:
            return PaneExitState(dead=True, status=int(status))
        except ValueError:
            return PaneExitState(dead=True, status=None)
