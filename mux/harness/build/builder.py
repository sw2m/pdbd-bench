from __future__ import annotations

from pathlib import Path

from harness.comparators import Comparator
from kit.remote import Remote


class Builder(Remote):
    runtime = ""
    binary: Path

    def build(self, version: str, picks: dict[Comparator, dict[str, str]]) -> str:
        raise NotImplementedError

    def prune(self) -> None:
        raise NotImplementedError

    def verify(self, picks: dict[Comparator, dict[str, str]]) -> None:
        for comparator, pick in picks.items():
            for impl in comparator.impls:
                built = self.said([str(self.binary), "version", impl])
                if built != pick["version"]:
                    raise RuntimeError(
                        f"{impl}: the {self.runtime} harness was built against {comparator.package} "
                        f"{built or 'nothing'}, not the resolved {pick['version']}"
                    )
