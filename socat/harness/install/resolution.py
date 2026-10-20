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
    def now(cls, pins: dict[str, str]) -> Resolution:
        names = {oracle.name for oracle in oracles}
        if not isinstance(pins, dict) or set(pins) - names:
            raise ValueError(f"pins must map {sorted(names)} to versions, got {pins!r}")
        if any(not isinstance(pin, str) for pin in pins.values()):
            raise ValueError(f"every pin is a version string, got {pins!r}")
        return cls({oracle.name: oracle.pick(pins.get(oracle.name, "")) for oracle in oracles})

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
        for oracle in oracles:
            oracle().run(self.picks[oracle.name])

    def dump(self) -> str:
        return json.dumps(self.picks, sort_keys=True)
