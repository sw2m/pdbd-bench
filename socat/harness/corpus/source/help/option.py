from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    name: str
    groups: tuple[str, ...]
    kind: str
    alias: str | None
