"""Text expectations for pane captures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import Pane


Duration = int | float | timedelta


@dataclass(frozen=True)
class TextMatch:
    """Location of text found in a pane capture."""

    text: str
    row: int
    column: int


class TextExpectation:
    """Deferred text assertion for a pane."""

    def __init__(
        self,
        pane: "Pane",
        *,
        mode: str | None = None,
        expected: str | None = None,
        interval: Duration = 0.05,
    ) -> None:
        self._pane = pane
        self._mode = mode
        self._expected = expected
        self._interval = interval

    def to_contain(self, text: str, *, interval: Duration = 0.05) -> "TextExpectation":
        """Expect the visible pane text to contain ``text``."""

        return TextExpectation(
            self._pane,
            mode="contains",
            expected=text,
            interval=interval,
        )

    def to_have_text(self, text: str, *, interval: Duration = 0.05) -> "TextExpectation":
        """Expect the visible pane text to equal ``text`` after trimming trailing newlines."""

        return TextExpectation(
            self._pane,
            mode="equals",
            expected=text,
            interval=interval,
        )

    def timeout(self, value: Duration) -> TextMatch:
        """Wait up to ``value`` for this expectation."""

        if self._mode is None or self._expected is None:
            raise ValueError("choose an expectation before setting a timeout")
        if self._mode == "contains":
            return self._pane.wait_for_text(
                self._expected,
                timeout=value,
                interval=self._interval,
            )
        if self._mode == "equals":
            return self._pane.wait_for_exact_text(
                self._expected,
                timeout=value,
                interval=self._interval,
            )
        raise ValueError(f"unknown text expectation mode: {self._mode}")


def duration_seconds(value: Duration) -> float:
    if isinstance(value, timedelta):
        seconds = value.total_seconds()
    else:
        seconds = float(value)
    if seconds < 0:
        raise ValueError("duration must be non-negative")
    return seconds


def row_column(text: str, index: int) -> tuple[int, int]:
    before = text[:index]
    row = before.count("\n")
    line_start = before.rfind("\n")
    if line_start < 0:
        return row, len(before)
    return row, len(before) - line_start - 1
