from __future__ import annotations

import json
from pathlib import Path

from harness.build.cargo import Cargo
from harness.build.golang import Golang
from harness.build.make import Make
from harness.build.maven import Maven
from harness.build.npm import Npm
from harness.build.nuget import Nuget
from harness.comparators import Comparator, comparators
from harness.resolution import Resolution

root = Path("/opt/mux")
peers = Path(__file__).resolve().parents[2] / "peers"


class Build:
    def __init__(self, resolution: Resolution) -> None:
        self.resolution = resolution
        self.builders = {
            "c": Make(root / "c", peers / "c"),
            "dotnet": Nuget(root / "dotnet", peers / "dotnet"),
            "go": Golang(root / "go", peers / "go"),
            "jvm": Maven(root / "jvm", peers / "jvm"),
            "node": Npm(root / "node", peers / "node"),
            "rust": Cargo(root / "rust", peers / "rust"),
        }

    def picks(self, runtime: str) -> dict[Comparator, dict[str, str]]:
        chosen = self.resolution.picks["comparators"]
        return {c: chosen[c.name] for c in comparators if c.runtime == runtime}

    def install(self) -> None:
        marker = root / "RESOLVED"
        if marker.exists() and marker.read_text().strip() == self.resolution.dump():
            for runtime, builder in self.builders.items():
                builder.verify(self.picks(runtime))
            return
        root.mkdir(parents=True, exist_ok=True)
        marker.unlink(missing_ok=True)
        toolchains = {}
        for runtime, builder in self.builders.items():
            version = self.resolution.picks["toolchains"].get(runtime, {}).get("version", "")
            toolchains[runtime] = builder.build(version, self.picks(runtime))
            builder.verify(self.picks(runtime))
            builder.prune()
        (root / "TOOLCHAINS").write_text(json.dumps(toolchains, sort_keys=True) + "\n")
        marker.write_text(self.resolution.dump() + "\n")
        print(f"mux: harnesses built for {', '.join(self.builders)} into {root}")

    @staticmethod
    def toolchains() -> dict[str, str]:
        return json.loads((root / "TOOLCHAINS").read_text())

    @staticmethod
    def resolved() -> dict:
        return json.loads((root / "RESOLVED").read_text())

    def binary(self, runtime: str) -> Path:
        return self.builders[runtime].binary
