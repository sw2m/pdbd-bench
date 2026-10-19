from __future__ import annotations

import os
import shutil
import signal
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

listen = 0.4 # s: past socat's parse, an open that blocks (a LISTEN in accept) has accepted the syntax
stuck = 5.0 # s: a stderr drain that outlasts the kill is a hung oracle
workers = 16 # one oracle process per input, each in its own network namespace so concurrent LISTENs never share a port
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
        found = shutil.which("unshare")
        if found is None:
            raise RuntimeError("no unshare on PATH: each oracle call needs its own network namespace")
        self.unshare = found

    def ask(self, text: str) -> str:
        child = subprocess.Popen(
            [self.unshare, "--net", str(self.binary), "-d", "-d", text, "/dev/null"],
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
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                stderr = child.communicate(timeout=stuck)[1]
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"{self.binary} on {text!r}: stderr still open {stuck} s after the kill") from None
        lines = stderr.splitlines()
        return "err" if any(p in line for line in lines for p in syntax) else "ok"

    def judge(self, texts: list[str]) -> list[str]:
        with ThreadPoolExecutor(workers) as pool:
            return list(pool.map(self.ask, texts))
