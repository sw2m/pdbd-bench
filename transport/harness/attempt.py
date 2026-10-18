from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from harness.cpus import Cpus
from harness.end import End
from harness.params import Params

near = "10.0.0.1"
far = "10.0.0.2"


class Attempt:
    def __init__(self, params: Params, cpus: Cpus, kinds: tuple[str, str], out: Path) -> None:
        self.params = params
        self.cpus = cpus
        self.out = out
        self.label = f"{kinds[0]} ↔ {kinds[1]}"
        self.near = End(kinds[0], True, out / "a", near, far, 1, out / "near.log")
        self.far = End(kinds[1], False, out / "b", far, near, 0, out / "far.log")
        self.bridge: subprocess.Popen[bytes] | None = None
        self.server: subprocess.Popen[bytes] | None = None

    def say(self, text: str) -> None:
        print(f"transport: {self.label}: {text}", file=sys.stderr, flush=True)

    @staticmethod
    def wait(check: Any, tries: int, pause: float) -> bool:
        for _ in range(tries):
            if check():
                return True
            time.sleep(pause)
        return False

    @staticmethod
    def quiet(*command: str) -> bool:
        return subprocess.run(command, capture_output=True).returncode == 0

    def up(self) -> float | None:
        self.out.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ip", "netns", "add", "near"], check=True)
        subprocess.run(["ip", "-n", "near", "link", "set", "lo", "up"], check=True)
        self.bridge = subprocess.Popen(
            [
                "socat",
                f"PTY,link={self.near.tty},raw,echo=0",
                f"PTY,link={self.far.tty},raw,echo=0",
            ]
        )
        self.wait(lambda: self.near.tty.exists() and self.far.tty.exists(), 100, 0.05)
        self.far.start(self.params)
        # see sw2m/pdbd#24
        self.wait(lambda: self.quiet("ip", "link", "show", self.far.device), 200, 0.05)
        start = time.monotonic()
        self.near.start(self.params)
        opened: dict[str, float] = {}
        for _ in range(3000):
            for side, end in (("near", self.near), ("far", self.far)):
                if side not in opened and end.opened():
                    opened[side] = time.monotonic()
            if len(opened) == 2:
                break
            time.sleep(0.01)
        if len(opened) < 2:
            self.say(f"L2 never opened (open: {', '.join(opened) or 'neither'})")
            return None
        if not self.wait(
            lambda: self.quiet("ip", "netns", "exec", "near", "ping", "-c1", "-W1", far), 40, 0.25
        ):
            self.say("L3 never answered after L2 opened")
            return None
        return (max(opened.values()) - start) * 1000

    def ping(self, count: int, wait: int) -> list[float]:
        done = subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                "near",
                "ping",
                "-c",
                str(count),
                "-i",
                "0.2",
                "-W",
                str(wait),
                far,
            ],
            capture_output=True,
            text=True,
        )
        return [float(t[5:]) for t in done.stdout.split() if t.startswith("time=")]

    def iperf(self, *flags: str) -> dict[str, Any]:
        done = subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                "near",
                "iperf3",
                "-c",
                far,
                "-t",
                str(self.params.duration),
                "-J",
                *flags,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        received: dict[str, Any] = json.loads(done.stdout)["end"]["sum_received"]
        return received

    def measure(self, bringup: float) -> dict[str, Any]:
        self.server = subprocess.Popen(
            ["iperf3", "-s", "-B", far], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self.wait(
            lambda: bool(
                subprocess.run(
                    ["ss", "-Hltn", f"src {far}:5201"], capture_output=True, text=True
                ).stdout
            ),
            50,
            0.1,
        )
        idle = self.ping(20, 5)
        before = self.cpus.busy()
        pinger = subprocess.Popen(
            [
                "sh",
                "-c",
                f"sleep 2; exec ip netns exec near ping -c {(self.params.duration - 3) * 5}"
                f" -i 0.2 -W 10 {far}",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        forward = self.iperf()
        output, _ = pinger.communicate()
        loaded = [float(t[5:]) for t in output.split() if t.startswith("time=")]
        reverse = self.iperf("-R")
        parallel = self.iperf("-P", "4")
        after = self.cpus.busy()
        runs = {"forward": forward, "reverse": reverse, "parallel": parallel}
        received = sum(r["bytes"] for r in runs.values())
        return {
            "bring-up": bringup,
            "throughput": {k: r["bits_per_second"] / 1e6 for k, r in runs.items()},
            "rtt": {"idle": idle, "loaded": loaded},
            "cpu": self.cpus.ms(before, after) / (received / 1e6),
        }

    def down(self) -> None:
        for end in (self.near, self.far):
            end.stop()
        for process in (self.server, self.bridge):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait()
        subprocess.run(["ip", "netns", "del", "near"], capture_output=True)

    def run(self) -> dict[str, Any] | None:
        try:
            bringup = self.up()
            return None if bringup is None else self.measure(bringup)
        except (subprocess.CalledProcessError, KeyError, ValueError) as error:
            self.say(f"failed: {error}")
            return None
        finally:
            self.down()
