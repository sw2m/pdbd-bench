from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from harness.build.builder import Builder
from harness.comparators import Comparator
from kit.toolchain import Dotnet


class Nuget(Builder):
    runtime = "dotnet"

    def __init__(self, root: Path, source: Path) -> None:
        self.root = root
        self.source = source
        self.toolchain = Dotnet(root / "toolchain")
        self.work = root / "build"

    @property
    def binary(self) -> Path:
        return self.root / "out" / "peer"

    def build(self, version: str, picks: dict[Comparator, dict[str, str]]) -> str:
        (comparator, pick), = picks.items()
        self.toolchain.install(version)
        shutil.rmtree(self.work, ignore_errors=True)
        shutil.rmtree(self.root / "out", ignore_errors=True)
        shutil.copytree(self.source, self.work)
        framework = f"net{version.split('.')[0]}.0"
        command = [
            str(self.toolchain.binary), "publish", "-c", "Release", "-r", self.toolchain.rid, "--self-contained",
            f"-p:Nerdbank={pick['version']}", f"-p:Framework={framework}", "-o", str(self.root / "out"),
        ]
        done = subprocess.run(command, capture_output=True, text=True, env=self.toolchain.env(), cwd=self.work)
        if done.returncode != 0 or not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"dotnet publish: exit {done.returncode}: {(done.stdout + done.stderr)[-600:]}")
        return f".NET SDK {version} ({framework}, self-contained)"

    def prune(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)
        self.toolchain.prune()
