from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Params:
    verdict: Path | None
    hand: Path | None
    alternatives: Path | None

    @classmethod
    def load(cls) -> Params:
        inputs = Path(os.environ["BENCHER_IN"])
        raw = json.loads((inputs / "params.json").read_text())
        artifacts = inputs / "artifacts"

        def artifact(name: str) -> Path | None:
            path = artifacts / name
            return path if path.exists() or path.is_symlink() else None

        verdict = artifact("verdict")
        if verdict is not None and (not verdict.is_file() or not os.access(verdict, os.X_OK)):
            raise RuntimeError(f"the verdict artifact {verdict} is not an executable file")
        for name in ("hand", "alternatives"):
            path = artifact(name)
            if path is not None and not path.is_file():
                raise RuntimeError(f"the {name} artifact {path} is not a file")
        unknown = set(raw) - {"pins"}
        if unknown:
            raise ValueError(f"the socat runner takes only pins, got {sorted(unknown)}")
        oracles = {"socat", "websocat", "oittaa", "tocat"}
        if set(raw.get("pins", {})) - oracles:
            raise ValueError(f"pins name an unknown oracle: {sorted(set(raw['pins']) - oracles)}")
        return cls(verdict=verdict, hand=artifact("hand"), alternatives=artifact("alternatives"))
