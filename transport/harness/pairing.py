from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from harness.attempt import Attempt
from harness.cpus import Cpus
from harness.params import Params


class Pairing:
    def __init__(self, name: str, params: Params, cpus: Cpus, work: Path) -> None:
        self.name = name
        self.params = params
        self.cpus = cpus
        self.work = work / name
        near, far = name.split(".")
        self.kinds = (near, far)

    def measure(self) -> list[dict[str, Any]]:
        self.work.mkdir(parents=True, exist_ok=True)
        results = self.work / "results.json"
        child = os.fork()
        if child == 0:
            Path(os.environ["BENCHER_REPORTERS"], f"{self.name}.pid").write_text(f"{os.getpid()}\n")
            found = []
            for i in range(self.params.repeat):
                found.append(Attempt(self.params, self.cpus, self.kinds, self.work / str(i)).run())
                time.sleep(1)
            results.write_text(json.dumps(found))
            os._exit(0)
        os.waitpid(child, 0)
        return (
            [r for r in json.loads(results.read_text()) if r is not None]
            if results.exists()
            else []
        )

    def tags(self) -> dict[str, str]:
        tags = {"pairing": self.name}
        if "pppd" in self.kinds:
            tags["pppd"] = self.params.version
        return tags

    def rows(self) -> list[dict[str, Any]]:
        runs = self.measure()
        tags = self.tags()
        rows: list[dict[str, Any]] = [
            {
                "name": "link",
                "tags": tags,
                "verdict": "ok" if len(runs) == self.params.repeat else "err",
            }
        ]
        if not runs:
            return rows
        rows.append(
            {"name": "bring-up", "tags": tags, "samples": {"ms": [r["bring-up"] for r in runs]}}
        )
        for direction in ("forward", "reverse", "parallel"):
            rows.append(
                {
                    "name": "throughput",
                    "tags": {**tags, "direction": direction},
                    "samples": {"Mbit/s": [r["throughput"][direction] for r in runs]},
                }
            )
        for load in ("idle", "loaded"):
            rows.append(
                {
                    "name": "rtt",
                    "tags": {**tags, "load": load},
                    "samples": {"ms": [t for r in runs for t in r["rtt"][load]]},
                }
            )
        rows.append(
            {
                "name": "cpu",
                "tags": tags,
                "reporter": self.name,
                "samples": {"ms/MB": [r["cpu"] for r in runs]},
            }
        )
        return rows
