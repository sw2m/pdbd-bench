from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    text: str
    family: str
