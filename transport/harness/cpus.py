from __future__ import annotations

import os
import time


class Cpus:
    def __init__(self) -> None:
        self.ids = sorted(os.sched_getaffinity(0))
        self.hz = os.sysconf("SC_CLK_TCK")

    def busy(self) -> tuple[float, int]:
        names = {f"cpu{i}" for i in self.ids}
        total = 0
        with open("/proc/stat") as stat:
            for line in stat:
                fields = line.split()
                if fields and fields[0] in names:
                    user, nice, system, _, _, irq, softirq, steal = (int(f) for f in fields[1:9])
                    total += user + nice + system + irq + softirq + steal
        return time.monotonic(), total

    def ms(self, before: tuple[float, int], after: tuple[float, int]) -> float:
        return (after[1] - before[1]) * 1000 / self.hz
