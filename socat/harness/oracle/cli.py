from __future__ import annotations

import os
import signal
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

listen = 0.4 # s: past socat's parse, an open that blocks (a LISTEN in accept) has accepted the syntax
workers = 16 # one oracle process per input
syntax = [
    "unknown device/address",
    "wrong number of parameters",
    "parseopts",
    "unknown option",
    "not supported with this address type",
    "not allowed without",
    "syntax error",
    "unbalanced",
    "missing numerical value",
    "nestlex",
    "parse left address",
    "parse right address",
]


class Cli:
    def __init__(self, binary: Path, sandbox: Path) -> None:
        self.binary = binary
        self.sandbox = sandbox

    def ask(self, text: str) -> str:
        child = subprocess.Popen(
            [str(self.binary), "-d", "-d", text, "/dev/null"],
            env={"PATH": "/nonexistent"},
            cwd=self.sandbox,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
        try:
            stderr = child.communicate(timeout=listen)[1]
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            stderr = child.communicate()[1]
        lines = stderr.splitlines()
        return "err" if any(p in line for line in lines for p in syntax) else "ok"

    def judge(self, texts: list[str]) -> list[str]:
        with ThreadPoolExecutor(workers) as pool:
            return list(pool.map(self.ask, texts))
