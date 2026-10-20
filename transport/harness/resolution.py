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
    def now(cls, inputs: Path) -> Resolution:
        pins = json.loads((inputs / "params.json").read_text()).get("pins", {})
        names = {build.name for build in builds}
        if not isinstance(pins, dict) or set(pins) - names:
            raise ValueError(f"pins must map {sorted(names)} to versions, got {pins!r}")
        if any(not isinstance(pin, str) for pin in pins.values()):
            raise ValueError(f"every pin is a version string, got {pins!r}")
        return cls({build.name: build.pick(pins.get(build.name, "")) for build in builds})

    @classmethod
    def load(cls, inputs: Path) -> Resolution:
        resolved = inputs / "resolved.json"
        if not resolved.exists():
            return cls.now(inputs)
        return cls(json.loads(resolved.read_text()))

    def install(self) -> None:
        for build in builds:
            build().run(self.picks[build.name])

    def dump(self) -> str:
        return json.dumps(self.picks, sort_keys=True)
