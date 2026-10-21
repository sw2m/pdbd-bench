from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from harness.build.builder import Builder
from harness.comparators import Comparator
from kit.toolchain import Go


class Golang(Builder):
    runtime = "go"

    def __init__(self, root: Path, source: Path) -> None:
        self.root = root
        self.source = source
        self.toolchain = Go(root / "toolchain")
        self.work = root / "build"

    @property
    def binary(self) -> Path:
        return self.root / "peer"

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "GOROOT": str(self.toolchain.root),
            "GOPATH": str(self.root / "gopath"),
            "GOCACHE": str(self.root / "cache"),
            "GOTOOLCHAIN": "local",
            "GOFLAGS": "-mod=mod",
            "PATH": f"{self.toolchain.binary.parent}:{os.environ.get('PATH', '')}",
        }

    def go(self, *args: str) -> str:
        done = subprocess.run(
            [str(self.toolchain.binary), *args], capture_output=True, text=True, env=self.env(), cwd=self.work
        )
        said = f"{done.stdout}{done.stderr}".strip()
        if done.returncode != 0:
            raise RuntimeError(f"go {' '.join(args)}: exit {done.returncode}: {said[-600:]}")
        return said

    def build(self, version: str, picks: dict[Comparator, dict[str, str]]) -> str:
        self.toolchain.install(version)
        shutil.rmtree(self.work, ignore_errors=True)
        shutil.copytree(self.source, self.work)
        for comparator, pick in picks.items():
            self.go("get", f"{comparator.package}@{pick['version']}")
        self.go("build", "-trimpath", "-o", str(self.binary), ".")
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"go build left no executable {self.binary}")
        return self.go("version").removeprefix("go version ")

    def prune(self) -> None:
        for path in (self.work, self.root / "gopath", self.root / "cache", self.toolchain.root):
            shutil.rmtree(path, ignore_errors=True)
