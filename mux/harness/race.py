from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from harness.comparators import named, streams
from harness.params import Params, ours

mib = 1 << 20
priced = ("bulk", "flows")  # see README.md "Scenarios"


@dataclass(frozen=True)
class Impl:
    name: str
    argv: tuple[str, ...]
    scenarios: tuple[str, ...]


@dataclass(frozen=True)
class Variant:
    scenario: str
    tags: tuple[tuple[str, str], ...] = ()

    def wire(self, params: Params) -> dict[str, int | float]:
        wire = params.wire()
        for key, value in self.tags:
            wire[key] = int(value)
        if self.scenario == "loaded":
            wire["pings"] = params.trips
        wire["limit"] = self.limit(params, wire)
        return wire

    def limit(self, params: Params, wire: dict[str, int | float]) -> int:
        streams = {
            "flows": int(wire.get("flows", 0)),
            "isolation": int(wire.get("flows", 0)),
            "loaded": params.busy + 1,
            "churn": params.churn,
            "idle": params.idle,
        }
        return streams.get(self.scenario, 1) + 1  # see README.md "Fairness": one spare stream


@dataclass
class Turn:
    verdict: str
    values: dict[str, float]


class Race:
    def __init__(self, params: Params, binaries: dict[str, Path]) -> None:
        self.params = params
        self.impls = [impl for impl in self.available(binaries) if impl.name in params.impls]
        self.turns: dict[tuple[str, tuple[tuple[str, str], ...], str], dict[int, Turn]] = {}

    def available(self, binaries: dict[str, Path]) -> list[Impl]:
        impls = []
        muxbench = self.params.muxbench
        if muxbench.exists() or muxbench.is_symlink():
            if not muxbench.is_file() or not os.access(muxbench, os.X_OK):
                raise RuntimeError(f"the muxbench artifact {muxbench} is not an executable file")
            impls += [Impl(mode, (str(muxbench), mode), (*streams, "udp")) for mode in ours]
        else:
            print("mux: no muxbench artifact, so only the comparators race", file=sys.stderr)
        for comparator in named.values():
            for impl in comparator.impls:
                impls.append(Impl(impl, (str(binaries[comparator.runtime]), impl), comparator.scenarios))
        return impls

    def variants(self) -> list[Variant]:
        out = []
        for scenario in self.params.scenarios:
            if scenario == "flows":
                out += [Variant("flows", (("flows", str(n)),)) for n in self.params.flows]
            elif scenario == "isolation":
                out.append(Variant("isolation", (("flows", str(self.params.isolated)),)))
            elif scenario == "udp":
                out += [Variant("udp", (("datagram", str(size)),)) for size in self.params.sizes]
            else:
                out.append(Variant(scenario))
        return out

    def run(self) -> None:
        variants = self.variants()
        for turn in range(self.params.repeat):
            shift = turn % len(self.impls)
            order = self.impls[shift:] + self.impls[:shift]  # see README.md "Statistics"
            for variant in variants:
                for impl in order:
                    if variant.scenario in impl.scenarios:
                        key = (variant.scenario, variant.tags, impl.name)
                        self.turns.setdefault(key, {})[turn] = self.measure(impl, variant)
            print(f"mux: repetition {turn + 1} of {self.params.repeat} done", file=sys.stderr)

    def measure(self, impl: Impl, variant: Variant) -> Turn:
        wire = variant.wire(self.params)
        argv = [*impl.argv, variant.scenario, json.dumps(wire)]
        runs = 4 if variant.scenario == "isolation" else 2  # see README.md "Statistics"
        limit = runs * self.params.timeout + 60
        what = f"{impl.name} {variant.scenario} {dict(variant.tags)}"
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            if variant.scenario == "isolation":
                return Turn("err", {})
            raise RuntimeError(f"{what}: no result within {limit:.0f} s") from None
        if done.returncode != 0:
            raise RuntimeError(f"{what}: exit {done.returncode}: {done.stderr.strip()[-800:]}")
        result = json.loads(done.stdout)
        if result["verdict"] != "ok":
            if variant.scenario == "isolation":
                return Turn("err", {})
            raise RuntimeError(f"{what}: verdict {result['verdict']}")
        values = {unit: float(value) for unit, value in result["values"].items()}
        cpu = values.pop("cpu ms")
        if variant.scenario in priced:
            values["ms/MiB"] = cpu / (wire["bulk"] / mib)
        return Turn("ok", values)

    def rows(self) -> list[dict]:
        rows = []
        for (scenario, tags, impl), turns in self.turns.items():
            ok = {turn: t.values for turn, t in turns.items() if t.verdict == "ok"}
            if scenario == "isolation":
                verdict = "ok" if len(ok) == len(turns) else "err"
                rows.append({"name": "isolated", "tags": {"impl": impl}, "verdict": verdict})
            if not ok:
                continue
            units = sorted({unit for values in ok.values() for unit in values})
            samples = {unit: [values[unit] for values in ok.values() if unit in values] for unit in units}
            rows.append({"name": scenario, "tags": {"impl": impl, **dict(tags)}, "samples": samples})
        return rows
