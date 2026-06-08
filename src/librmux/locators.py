"""Text locators for pane snapshots."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .expectations import Duration, TextMatch, duration_seconds

if TYPE_CHECKING:
    from .server import Pane


@dataclass(frozen=True)
class TextLocator:
    """A text query scoped to one pane."""

    pane: "Pane"
    text: str
    index: int | None = None

    def all(self) -> tuple[TextMatch, ...]:
        """Return all current matches."""

        return self.pane.snapshot().find_all_text(self.text)

    def count(self) -> int:
        """Return the current number of matches."""

        return len(self.all())

    def first(self) -> "TextLocator":
        """Return a locator for the first match."""

        return TextLocator(self.pane, self.text, 0)

    def last(self) -> "TextLocator":
        """Return a locator for the last match."""

        return TextLocator(self.pane, self.text, -1)

    def nth(self, index: int) -> "TextLocator":
        """Return a locator for a zero-based match."""

        return TextLocator(self.pane, self.text, index)

    def is_visible(self) -> bool:
        """Return whether this locator currently resolves to a match."""

        return self._resolve(self.all()) is not None

    def expect(self) -> "LocatorExpectation":
        """Create an expectation for this locator."""

        return LocatorExpectation(self)

    def _resolve(self, matches: tuple[TextMatch, ...]) -> TextMatch | None:
        if self.index is None:
            return matches[0] if matches else None
        try:
            return matches[self.index]
        except IndexError:
            return None


class LocatorExpectation:
    """Deferred assertion for a text locator."""

    def __init__(
        self,
        locator: TextLocator,
        *,
        mode: str | None = None,
        expected: str | int | None = None,
        interval: Duration = 0.05,
    ) -> None:
        self._locator = locator
        self._mode = mode
        self._expected = expected
        self._interval = interval

    def to_be_visible(self, *, interval: Duration = 0.05) -> "LocatorExpectation":
        """Expect this locator to resolve to at least one visible match."""

        return LocatorExpectation(self._locator, mode="visible", interval=interval)

    def to_have_text(
        self,
        text: str,
        *,
        interval: Duration = 0.05,
    ) -> "LocatorExpectation":
        """Expect this locator's resolved match text to equal ``text``."""

        return LocatorExpectation(
            self._locator,
            mode="text",
            expected=text,
            interval=interval,
        )

    def to_have_count(
        self,
        count: int,
        *,
        interval: Duration = 0.05,
    ) -> "LocatorExpectation":
        """Expect this locator to resolve to ``count`` matches."""

        return LocatorExpectation(
            self._locator,
            mode="count",
            expected=count,
            interval=interval,
        )

    def timeout(self, value: Duration) -> TextMatch | int:
        """Wait up to ``value`` for this expectation."""

        if self._mode is None:
            raise ValueError("choose an expectation before setting a timeout")
        timeout_seconds = duration_seconds(value)
        interval_seconds = duration_seconds(self._interval)
        deadline = time.monotonic() + timeout_seconds
        last_count = 0
        while True:
            matches = self._locator.all()
            last_count = len(matches)
            match = self._locator._resolve(matches)
            if self._mode == "visible" and match is not None:
                return match
            if self._mode == "text" and match is not None:
                if match.text == self._expected:
                    return match
            if self._mode == "count" and last_count == self._expected:
                return last_count
            if time.monotonic() >= deadline:
                raise AssertionError(self._failure_message(last_count))
            time.sleep(interval_seconds)

    def _failure_message(self, last_count: int) -> str:
        if self._mode == "visible":
            return f"text not visible before timeout: {self._locator.text!r}"
        if self._mode == "text":
            return (
                "text locator did not resolve to expected text before timeout: "
                f"{self._locator.text!r} != {self._expected!r}"
            )
        if self._mode == "count":
            return (
                "text locator count did not match before timeout: "
                f"{last_count} != {self._expected}"
            )
        return "locator expectation failed before timeout"
