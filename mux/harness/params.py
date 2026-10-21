from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from harness.comparators import impls, streams

scenarios = (*streams, "udp")
ours = ("core", "loopback")


@dataclass(frozen=True)
class Params:
    repeat: int = 7  # see README.md "Statistics"
    timeout: float = 60.0
    window: int = 256 * 1024
    chunk: int = 64 * 1024
    bulk: int = 256 << 20
    flows: tuple[int, ...] = (16, 256)
    isolated: int = 16
    message: int = 64
    pings: int = 10_000
    lead: int = 100
    busy: int = 4
    churn: int = 1000
    idle: int = 1000
    datagrams: int = 200_000
    sizes: tuple[int, ...] = (64, 512, 1400)
    budget: int = 64 << 20
    impls: tuple[str, ...] = (*ours, *impls)
    scenarios: tuple[str, ...] = scenarios
    muxbench: Path = field(default=Path("/nonexistent"))

    @classmethod
    def load(cls) -> Params:
        inputs = Path(os.environ["BENCHER_IN"])
        raw = json.loads((inputs / "params.json").read_text())
        raw.pop("pins", None)
        unknown = set(raw) - (set(cls.__dataclass_fields__) - {"muxbench"})
        if unknown:
            raise ValueError(f"params name unknown keys: {sorted(unknown)}")
        for key in ("flows", "sizes", "impls", "scenarios"):
            if key in raw:
                raw[key] = tuple(raw[key])
        params = cls(**raw, muxbench=inputs / "artifacts" / "muxbench")
        params.check()
        return params

    def check(self) -> None:
        if self.repeat < 1:
            raise ValueError(f"repeat is {self.repeat}: one repetition at least")
        if self.isolated < 2:
            raise ValueError(f"isolated is {self.isolated}: isolation needs a stalled flow and at least one other")
        if self.isolated not in self.flows:
            raise ValueError(f"isolated is {self.isolated}, not one of flows {self.flows}: its ratio has no baseline")
        if self.pings < 1000:
            raise ValueError(f"pings is {self.pings}: a p99.9 needs at least 1000 round trips")
        unknown = set(self.impls) - {*ours, *impls}
        if unknown:
            raise ValueError(f"impls names unknown impls: {sorted(unknown)}")
        unknown = set(self.scenarios) - set(scenarios)
        if unknown:
            raise ValueError(f"scenarios names unknown scenarios: {sorted(unknown)}")

    def wire(self) -> dict[str, int | float]:
        return {
            "window": self.window,
            "chunk": self.chunk,
            "bulk": self.bulk,
            "message": self.message,
            "pings": self.pings,
            "warm": self.lead,
            "load": self.busy,
            "churn": self.churn,
            "idle": self.idle,
            "datagrams": self.datagrams,
            "budget": self.budget,
            "timeout": self.timeout,
        }
