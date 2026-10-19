from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Head:
    name: str
    signature: str
    groups: tuple[str, ...]
    alias: str | None
