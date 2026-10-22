from __future__ import annotations

import json
from pathlib import Path

from harness.comparators import named, runtimes
from kit.toolchain import Dotnet, Go, Jdk, Node, Rust

modes = {"floating", "pinned"}
toolchains = {"dotnet": Dotnet, "go": Go, "jvm": Jdk, "node": Node, "rust": Rust}
managed = sorted(runtime for runtime in runtimes if runtime in toolchains)  # see README.md "Build"


class Resolution:
    def __init__(self, picks: dict[str, dict[str, dict[str, str]]]) -> None:
        if set(picks) != {"comparators", "toolchains"}:
            raise ValueError(f"resolved.json holds {sorted(picks)}, not comparators and toolchains")
        comparators, tools = picks["comparators"], picks["toolchains"]
        if set(comparators) != set(named):
            raise ValueError(f"resolved.json names {sorted(comparators)}, not the comparators {sorted(named)}")
        if set(tools) != set(managed):
            raise ValueError(f"resolved.json's toolchains are {sorted(tools)}, not {managed}")
        for name, pick in comparators.items():
            if not isinstance(pick, dict) or set(pick) != {"version", "mode"}:
                raise ValueError(f"resolved.json's {name} is {pick!r}: it takes exactly version and mode")
            if pick["mode"] not in modes or not isinstance(pick["version"], str) or not pick["version"]:
                raise ValueError(f"resolved.json's {name} is {pick!r}: a version, and mode one of {sorted(modes)}")
        for runtime, pick in tools.items():
            if not isinstance(pick, dict) or set(pick) != {"version"} or not pick["version"]:
                raise ValueError(f"resolved.json's {runtime} toolchain is {pick!r}: it takes exactly a version")
        self.picks = picks

    @staticmethod
    def check(pins: dict[str, str]) -> None:
        if not isinstance(pins, dict):
            raise ValueError(f"pins is {pins!r}, not a table of versions")
        unknown = set(pins) - set(named)
        if unknown:
            raise ValueError(f"pins name an unknown comparator: {sorted(unknown)}")
        if any(not isinstance(pin, str) or not pin for pin in pins.values()):
            raise ValueError(f"every pin is a version string, got {pins!r}")

    @classmethod
    def now(cls, pins: dict[str, str]) -> Resolution:
        cls.check(pins)
        comparators = {
            name: {"version": pins[name], "mode": "pinned"}
            if name in pins
            else {"version": comparator.latest(), "mode": "floating"}
            for name, comparator in named.items()
        }
        tools = {runtime: {"version": toolchains[runtime].latest()} for runtime in managed}
        return cls({"comparators": comparators, "toolchains": tools})

    @classmethod
    def load(cls, inputs: Path, phase: str) -> Resolution:
        pins = json.loads((inputs / "params.json").read_text()).get("pins", {})
        resolved = inputs / "resolved.json"
        picks = json.loads(resolved.read_text()) if resolved.exists() else {}
        if not picks:
            if phase == "prime":
                raise ValueError(
                    "a provisioned image needs the consumer's resolved.json (bench.toml resolved), "
                    "or it would cache whatever is latest today: see the repo's README, \"Runners\""
                )
            return cls.now(pins)
        resolution = cls(picks)
        resolution.agree(pins)
        return resolution

    def agree(self, pins: dict[str, str]) -> None:
        self.check(pins)
        for name, pin in pins.items():
            pick = self.picks["comparators"][name]
            if pick["mode"] != "pinned" or pick["version"] != pin:
                raise ValueError(
                    f"params.pins.{name} is {pin!r}, but resolved.json's {name} is {pick!r}: "
                    "pin it in bench.toml (resolve doesn't see a --set) and regenerate resolved.json"
                )

    def dump(self) -> str:
        return json.dumps(self.picks, sort_keys=True)
