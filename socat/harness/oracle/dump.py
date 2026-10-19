from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

resolve = 3.0 # s: websocat resolves host names while building the spec; one still running has parsed it
workers = 16 # one oracle process per input


class Dump:
    def __init__(self, binary: Path, sandbox: Path) -> None:
        self.binary = binary
        self.sandbox = sandbox

    def ask(self, text: str) -> str:
        child = subprocess.Popen(
            [str(self.binary), "-t", "-E", "--dump-spec", text, "-"],
            env={"PATH": "/nonexistent"},
            cwd=self.sandbox,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            return "ok" if child.wait(timeout=resolve) == 0 else "err"
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            return "ok"

    def judge(self, texts: list[str]) -> list[str]:
        with ThreadPoolExecutor(workers) as pool:
            return list(pool.map(self.ask, texts))
