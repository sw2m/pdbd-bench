from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from harness.build.builder import Builder
from harness.comparators import Comparator
from kit.toolchain import Rust


class Cargo(Builder):
    runtime = "rust"

    def __init__(self, root: Path, source: Path) -> None:
        self.root = root
        self.source = source
        self.toolchain = Rust(root / "toolchain")
        self.work = root / "build"

    @property
    def binary(self) -> Path:
        return self.root / "peer"

    def cargo(self, *args: str) -> str:
        env = {**self.toolchain.env(), "CARGO_TARGET_DIR": str(self.work / "target")}
        done = subprocess.run(["cargo", *args], capture_output=True, text=True, env=env, cwd=self.work)
        said = f"{done.stdout}{done.stderr}".strip()
        if done.returncode != 0:
            raise RuntimeError(f"cargo {' '.join(args)}: exit {done.returncode}: {said[-600:]}")
        return said

    def build(self, version: str, picks: dict[Comparator, dict[str, str]]) -> str:
        self.toolchain.install(version)
        shutil.rmtree(self.work, ignore_errors=True)
        shutil.copytree(self.source, self.work)
        self.cargo("generate-lockfile")
        for comparator, pick in picks.items():
            self.cargo("update", "-p", comparator.package, "--precise", pick["version"])
        self.cargo("build", "--release", "--locked")
        shutil.copy2(self.work / "target" / "release" / "peer", self.binary)
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"cargo build left no executable {self.binary}")
        return self.said(["rustc", "--version"], env=self.toolchain.env())

    def prune(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)
        self.toolchain.prune()
