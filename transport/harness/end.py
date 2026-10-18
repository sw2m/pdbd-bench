from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness.params import Params

# see https://github.com/sw2m/ppproto/blob/2a60894/src/ppp/mod.rs#L145-L148
markers = {"pppd": "local  IP address", "linkup": "phase: Open"}


@dataclass
class End:
    kind: str
    near: bool
    tty: Path
    local: str
    peer: str
    unit: int
    log: Path
    process: subprocess.Popen[bytes] | None = None

    @property
    def device(self) -> str:
        return f"ppp{self.unit}" if self.kind == "pppd" else f"pdbd{self.unit}"

    def command(self, params: Params) -> list[str]:
        prefix = ["ip", "netns", "exec", "near"] if self.near else []
        if self.kind == "pppd":
            return [
                *prefix,
                str(params.pppd),
                str(self.tty),
                str(params.baud),
                "noauth",
                "local",
                "nodetach",
                "nocrtscts",
                "novj",
                "noccp",
                "nolock",
                "debug",
                "lcp-echo-interval",
                "0",
                "unit",
                str(self.unit),
                "logfile",
                str(self.log),
                f"{self.local}:{self.peer}",
            ]
        return [*prefix, str(params.linkup), str(self.tty), self.local, self.peer, self.device]

    def start(self, params: Params) -> None:
        env = {**os.environ, "PDBD_BAUD": str(params.baud)}
        with self.log.open("ab") as log:
            self.process = subprocess.Popen(
                self.command(params), env=env, stdout=subprocess.DEVNULL, stderr=log
            )

    def check(self) -> None:
        if self.process is None or self.process.poll() is None:
            return
        try:
            tail = " | ".join(self.log.read_text(errors="replace").strip().splitlines()[-3:])
        except FileNotFoundError:
            tail = "no log"
        side = "near" if self.near else "far"
        raise RuntimeError(
            f"{self.kind} ({side}) exited {self.process.returncode} before the link opened: {tail}"
        )

    def opened(self) -> bool:
        try:
            return markers[self.kind] in self.log.read_text(errors="replace")
        except FileNotFoundError:
            return False

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
