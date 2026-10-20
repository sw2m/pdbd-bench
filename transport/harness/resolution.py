from __future__ import annotations

import json
from pathlib import Path

from harness.build import Build

builds = (Build,)
modes = {"floating", "pinned"}


class Resolution:
    def __init__(self, picks: dict[str, dict[str, str]]) -> None:
        names = {build.name for build in builds}
        if set(picks) != names:
            raise ValueError(f"resolved.json names {sorted(picks)}, not the builds {sorted(names)}")
        for build in builds:
            pick = picks[build.name]
            if not isinstance(pick, dict) or set(pick) != set(build.keys):
                raise ValueError(f"resolved.json's {build.name} is {pick!r}: it takes exactly {list(build.keys)}")
            if any(not isinstance(value, str) or not value for value in pick.values()):
                raise ValueError(f"resolved.json's {build.name} is {pick!r}: every value is a non-empty string")
            if pick["mode"] not in modes:
                raise ValueError(f"resolved.json's {build.name} has mode {pick['mode']!r}, not one of {sorted(modes)}")
        self.picks = picks

    @staticmethod
    def check(pins: dict[str, str]) -> None:
        if not isinstance(pins, dict):
            raise ValueError(f"pins is {pins!r}, not a table of versions")
        unknown = set(pins) - {build.name for build in builds}
        if unknown:
            raise ValueError(f"pins name an unknown build: {sorted(unknown)}")
        if any(not isinstance(pin, str) for pin in pins.values()):
            raise ValueError(f"every pin is a version string, got {pins!r}")

    @classmethod
    def now(cls, pins: dict[str, str]) -> Resolution:
        cls.check(pins)
        return cls({build.name: build.pick(pins.get(build.name, "")) for build in builds})

    @classmethod
    def load(cls, inputs: Path, phase: str) -> Resolution:
        pins = json.loads((inputs / "params.json").read_text()).get("pins", {})
        resolved = inputs / "resolved.json"
        picks = json.loads(resolved.read_text()) if resolved.exists() else {}
        if not picks:
            if phase == "prime":
                raise ValueError(
                    "a provisioned image needs the consumer's resolved.json (bench.toml resolved), "
                    "or it would cache whatever is latest today: see README \"Runners\""
                )
            return cls.now(pins)
        resolution = cls(picks)
        resolution.agree(pins)
        return resolution

    def agree(self, pins: dict[str, str]) -> None:
        self.check(pins)
        for name, pin in pins.items():
            pick = self.picks[name]
            if pick["mode"] != "pinned" or pick["version"] != pin:
                raise ValueError(
                    f"params.pins.{name} is {pin!r}, but resolved.json's {name} is {pick!r}: "
                    "pin it in bench.toml (resolve doesn't see a --set) and regenerate resolved.json"
                )

    def install(self) -> None:
        for build in builds:
            build().run(self.picks[build.name])

    def dump(self) -> str:
        return json.dumps(self.picks, sort_keys=True)
