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
            raise RuntimeError(f"resolved.json names {sorted(picks)}, not the builds {sorted(names)}")
        for build in builds:
            pick = picks[build.name]
            missing = [key for key in build.keys if not isinstance(pick.get(key), str) or not pick[key]]
            if missing or pick["mode"] not in modes:
                raise RuntimeError(f"resolved.json's {build.name} is {pick!r}: it needs {list(build.keys)}")
        self.picks = picks

    @classmethod
    def now(cls, pins: dict[str, str]) -> Resolution:
        names = {build.name for build in builds}
        if not isinstance(pins, dict) or set(pins) - names:
            raise ValueError(f"pins must map {sorted(names)} to versions, got {pins!r}")
        if any(not isinstance(pin, str) for pin in pins.values()):
            raise ValueError(f"every pin is a version string, got {pins!r}")
        return cls({build.name: build.pick(pins.get(build.name, "")) for build in builds})

    @classmethod
    def load(cls, inputs: Path, phase: str) -> Resolution:
        resolved = inputs / "resolved.json"
        picks = json.loads(resolved.read_text()) if resolved.exists() else {}
        if picks:
            return cls(picks)
        if phase == "prime":
            raise RuntimeError(
                "a provisioned image needs the consumer's resolved.json (bench.toml resolved), "
                "or it would cache whatever is latest today: see README \"Runners\""
            )
        return cls.now(json.loads((inputs / "params.json").read_text()).get("pins", {}))

    def install(self) -> None:
        for build in builds:
            build().run(self.picks[build.name])

    def dump(self) -> str:
        return json.dumps(self.picks, sort_keys=True)
