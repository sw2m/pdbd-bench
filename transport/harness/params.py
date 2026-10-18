from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from harness.build import Build

defaults = ["pppd.pppd", "linkup.linkup", "linkup.pppd"]


@dataclass(frozen=True)
class Params:
    pairings: list[str]
    repeat: int
    duration: int
    baud: int
    linkup: Path
    pppd: Path
    version: str
    mode: str
    toolchain: str
    sha256: str

    @classmethod
    def load(cls) -> Params:
        inputs = Path(os.environ["BENCHER_IN"])
        raw = json.loads((inputs / "params.json").read_text())
        build = Build()
        duration = int(raw.get("duration", 10))
        if duration < 4:
            raise ValueError(f"duration is {duration}: the loaded pings need at least 4 s")
        return cls(
            pairings=list(raw.get("pairings", defaults)),
            repeat=int(raw.get("repeat", 3)),
            duration=duration,
            baud=int(raw.get("baud", 115200)),
            linkup=inputs / "artifacts" / "linkup",
            pppd=build.binary,
            version=(build.prefix / "VERSION").read_text().strip(),
            mode=(build.prefix / "MODE").read_text().strip(),
            toolchain=(build.prefix / "TOOLCHAIN").read_text().strip(),
            sha256=(build.prefix / "SHA256").read_text().strip(),
        )

    def runnable(self) -> list[str]:
        if not self.linkup.exists():
            return [p for p in self.pairings if "linkup" not in p.split(".")]
        if not self.linkup.is_file() or not os.access(self.linkup, os.X_OK):
            raise RuntimeError(f"the linkup artifact {self.linkup} is not an executable file")
        return self.pairings
