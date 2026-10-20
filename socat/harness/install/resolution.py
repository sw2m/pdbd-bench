from __future__ import annotations

import json
from pathlib import Path

from harness.install.oittaa import Oittaa
from harness.install.socat import Socat
from harness.install.tocat import Tocat
from harness.install.websocat import Websocat

oracles = (Socat, Websocat, Oittaa, Tocat)


class Resolution:
    def __init__(self, picks: dict[str, dict[str, str]]) -> None:
        self.picks = picks

    @classmethod
    def now(cls, inputs: Path) -> Resolution:
        pins = json.loads((inputs / "params.json").read_text()).get("pins", {})
        return cls({oracle.name: oracle.pick(str(pins.get(oracle.name, ""))) for oracle in oracles})

    @classmethod
    def load(cls, inputs: Path) -> Resolution:
        resolved = inputs / "resolved.json"
        picks = json.loads(resolved.read_text()) if resolved.exists() else {}
        return cls(picks) if picks else cls.now(inputs)

    def install(self) -> None:
        for oracle in oracles:
            oracle().run(self.picks[oracle.name])

    def dump(self) -> str:
        return json.dumps(self.picks, sort_keys=True)
