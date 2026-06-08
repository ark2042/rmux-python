"""Typed pane snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from .expectations import TextMatch, row_column


@dataclass(frozen=True)
class PaneSnapshot:
    """Captured visible pane text with helper lookups."""

    visible_text: str

    @property
    def lines(self) -> tuple[str, ...]:
        """Return visible text split into rows."""

        return tuple(self.visible_text.splitlines())

    def row_text(self, row: int) -> str:
        """Return one row of visible text."""

        return self.lines[row]

    def find_text(self, text: str) -> TextMatch | None:
        """Return the first visible occurrence of ``text``."""

        index = self.visible_text.find(text)
        if index < 0:
            return None
        row, column = row_column(self.visible_text, index)
        return TextMatch(text=text, row=row, column=column)

    def find_all_text(self, text: str) -> tuple[TextMatch, ...]:
        """Return all non-overlapping visible occurrences of ``text``."""

        if text == "":
            return ()
        matches: list[TextMatch] = []
        start = 0
        while True:
            index = self.visible_text.find(text, start)
            if index < 0:
                return tuple(matches)
            row, column = row_column(self.visible_text, index)
            matches.append(TextMatch(text=text, row=row, column=column))
            start = index + len(text)
