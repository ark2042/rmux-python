"""Pane group helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from .expectations import Duration, duration_seconds
from .handles import Pane
from .snapshots import PaneSnapshot

if TYPE_CHECKING:
    from .server import CommandRun


@dataclass(frozen=True)
class PaneSetOutcome:
    """Visible-text wait result for a pane set."""

    matched: tuple[Pane, ...]
    snapshots: tuple[PaneSnapshot, ...]


class PaneSet:
    """Ordered group of pane handles."""

    def __init__(self, panes: Iterable[Pane]) -> None:
        self._panes = tuple(panes)

    @property
    def panes(self) -> tuple[Pane, ...]:
        """Return panes in caller order."""

        return self._panes

    def __len__(self) -> int:
        return len(self._panes)

    def __iter__(self):
        return iter(self._panes)

    def is_empty(self) -> bool:
        """Return whether this pane set has no panes."""

        return not self._panes

    def broadcast_text(self, text: str) -> tuple["CommandRun", ...]:
        """Send literal text to every pane."""

        return tuple(pane.send_text(text) for pane in self._panes)

    def broadcast_key(self, key: str) -> tuple["CommandRun", ...]:
        """Send one key token to every pane."""

        return tuple(pane.send_keys(key) for pane in self._panes)

    def snapshot_all(self) -> tuple[PaneSnapshot, ...]:
        """Capture one snapshot per pane."""

        return tuple(pane.snapshot() for pane in self._panes)

    def expect_all(self) -> "PaneSetExpectation":
        """Start an all-panes expectation."""

        return PaneSetExpectation(self, mode="all")

    def expect_any(self) -> "PaneSetExpectation":
        """Start an any-pane expectation."""

        return PaneSetExpectation(self, mode="any")

    def wait_all(self) -> "PaneSetExpectation":
        """Alias for ``expect_all``."""

        return self.expect_all()

    def wait_any(self) -> "PaneSetExpectation":
        """Alias for ``expect_any``."""

        return self.expect_any()


class PaneSetExpectation:
    """Deferred visible-text expectation for a pane set."""

    def __init__(
        self,
        pane_set: PaneSet,
        *,
        mode: str,
        text: str | None = None,
        interval: Duration = 0.05,
    ) -> None:
        self._pane_set = pane_set
        self._mode = mode
        self._text = text
        self._interval = interval

    def visible_text_contains(
        self,
        text: str,
        *,
        interval: Duration = 0.05,
    ) -> "PaneSetExpectation":
        """Expect pane visible text to contain ``text``."""

        return PaneSetExpectation(
            self._pane_set,
            mode=self._mode,
            text=text,
            interval=interval,
        )

    def timeout(self, value: Duration) -> PaneSetOutcome:
        """Wait up to ``value`` for this pane-set expectation."""

        if self._text is None:
            raise ValueError("choose an expectation before setting a timeout")
        timeout_seconds = duration_seconds(value)
        interval_seconds = duration_seconds(self._interval)
        deadline = time.monotonic() + timeout_seconds
        while True:
            matched: list[Pane] = []
            snapshots: list[PaneSnapshot] = []
            for pane in self._pane_set:
                snapshot = pane.snapshot()
                if self._text in snapshot.visible_text:
                    matched.append(pane)
                    snapshots.append(snapshot)
            if self._mode == "all" and len(matched) == len(self._pane_set):
                return PaneSetOutcome(tuple(matched), tuple(snapshots))
            if self._mode == "any" and matched:
                return PaneSetOutcome(tuple(matched), tuple(snapshots))
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"pane set did not match visible text before timeout: {self._text!r}"
                )
            time.sleep(interval_seconds)
