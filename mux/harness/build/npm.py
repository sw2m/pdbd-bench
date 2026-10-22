from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from harness.build.builder import Builder
from harness.comparators import Comparator
from kit.toolchain import Node


class Npm(Builder):
    runtime = "node"

    def __init__(self, root: Path, source: Path) -> None:
        self.root = root
        self.source = source
        self.toolchain = Node(root / "toolchain")
        self.app = root / "app"

    @property
    def binary(self) -> Path:
        return self.root / "peer"

    def build(self, version: str, picks: dict[Comparator, dict[str, str]]) -> str:
        self.toolchain.install(version)
        shutil.rmtree(self.app, ignore_errors=True)
        shutil.copytree(self.source, self.app)
        npm = self.toolchain.root / "bin" / "npm"
        exact = [f"{c.package}@{pick['version']}" for c, pick in picks.items()]
        command = [str(npm), "install", "--no-audit", "--no-fund", "--save-exact", *exact]
        done = subprocess.run(command, capture_output=True, text=True, env=self.toolchain.env(), cwd=self.app)
        if done.returncode != 0:
            said = (done.stdout + done.stderr)[-600:]
            raise RuntimeError(f"npm install {' '.join(exact)}: exit {done.returncode}: {said}")
        # see README.md "Build"
        self.binary.write_text(f'#!/bin/sh\nexec {self.toolchain.binary} --expose-gc {self.app / "peer.mjs"} "$@"\n')
        self.binary.chmod(0o755)
        return f"node {version}"

    def verify(self, picks: dict[Comparator, dict[str, str]]) -> None:
        super().verify(picks)
        if not os.access(self.toolchain.binary, os.X_OK):
            raise RuntimeError(f"{self.toolchain.binary} is gone: the Node harness needs it at run time")
    def prune(self) -> None:
        self.toolchain.prune()
