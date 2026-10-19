from __future__ import annotations

from collections.abc import Iterable

from harness.corpus.entry import Entry


class Corpus:
    def __init__(self) -> None:
        self.entries: list[Entry] = []
        self.seen: set[str] = set()

    def add(self, entries: Iterable[Entry]) -> None:
        for entry in entries:
            if not entry.text or "\0" in entry.text or entry.text in self.seen:
                continue
            self.seen.add(entry.text)
            self.entries.append(entry)
