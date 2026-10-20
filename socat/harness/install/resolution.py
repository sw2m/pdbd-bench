from __future__ import annotations

import json
from pathlib import Path

from harness.install.oittaa import Oittaa
from harness.install.socat import Socat
from harness.install.tocat import Tocat
from harness.install.websocat import Websocat

oracles = (Socat, Websocat, Oittaa, Tocat)
modes = {"floating", "pinned"}


class Resolution:
    def __init__(self, picks: dict[str, dict[str, str]]) -> None:
        names = {oracle.name for oracle in oracles}
        if set(picks) != names:
            raise RuntimeError(f"resolved.json names {sorted(picks)}, not the oracles {sorted(names)}")
        for oracle in oracles:
            pick = picks[oracle.name]
            missing = [key for key in oracle.keys if not isinstance(pick.get(key), str) or not pick[key]]
            if missing or pick["mode"] not in modes:
                raise RuntimeError(f"resolved.json's {oracle.name} is {pick!r}: it needs {list(oracle.keys)}")
        self.picks = picks

    @classmethod
    def now(cls, inputs: Path) -> Resolution:
        pins = json.loads((inputs / "params.json").read_text()).get("pins", {})
        names = {oracle.name for oracle in oracles}
        if not isinstance(pins, dict) or set(pins) - names:
            raise ValueError(f"pins must map {sorted(names)} to versions, got {pins!r}")
        if any(not isinstance(pin, str) for pin in pins.values()):
            raise ValueError(f"every pin is a version string, got {pins!r}")
        return cls({oracle.name: oracle.pick(pins.get(oracle.name, "")) for oracle in oracles})

    @classmethod
    def load(cls, inputs: Path) -> Resolution:
        resolved = inputs / "resolved.json"
        if not resolved.exists():
            return cls.now(inputs)
        return cls(json.loads(resolved.read_text()))

    def install(self) -> None:
        for oracle in oracles:
            oracle().run(self.picks[oracle.name])

    def dump(self) -> str:
        return json.dumps(self.picks, sort_keys=True)
