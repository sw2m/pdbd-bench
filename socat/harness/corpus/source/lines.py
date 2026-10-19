from __future__ import annotations

import json
from collections.abc import Iterator

from harness.corpus.entry import Entry


class Lines:
    def __init__(self, text: str, origin: str) -> None:
        self.text = text
        self.origin = origin

    def entries(self) -> Iterator[Entry]:
        family = f"{self.origin}:misc"
        for number, line in enumerate(self.text.splitlines(), start=1):
            if line.startswith("# "):
                family = f"{self.origin}:{line[2:].strip()}"
            elif line:
                try:
                    text = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{self.origin}:{number}: not a JSON string: {error}") from None
                if not isinstance(text, str):
                    raise ValueError(f"{self.origin}:{number}: not a JSON string")
                yield Entry(text, family)
