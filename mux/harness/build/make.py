from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from harness.build.builder import Builder
from harness.comparators import Comparator

releases = "https://github.com/{package}/releases/download/v{version}"


class Make(Builder):
    runtime = "c"

    def __init__(self, root: Path, source: Path) -> None:
        self.root = root
        self.source = source
        self.prefix = root / "nghttp2"

    @property
    def binary(self) -> Path:
        return self.root / "peer"

    def run(self, command: list[str], cwd: Path) -> str:
        done = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
        said = f"{done.stdout}{done.stderr}".strip()
        if done.returncode != 0:
            raise RuntimeError(f"{' '.join(command[:2])}: exit {done.returncode}: {said[-600:]}")
        return said

    def build(self, version: str, picks: dict[Comparator, dict[str, str]]) -> str:
        (comparator, pick), = picks.items()
        release = releases.format(package=comparator.package, version=pick["version"])
        name = f"nghttp2-{pick['version']}.tar.xz"
        sums = self.read(f"{release}/checksums.txt").decode()
        listed = next((line.split()[0] for line in sums.splitlines() if line.endswith(f"  {name}")), None)
        if listed is None:
            raise RuntimeError(f"{release}/checksums.txt lists no {name}")
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root) as work:
            tarball = Path(work, name)
            digest = self.fetch(f"{release}/{name}", tarball)
            if digest != listed:
                raise RuntimeError(f"{name}: sha256 {digest}, checksums.txt lists {listed}")
            self.unpack(tarball, Path(work))
            tree = Path(work, f"nghttp2-{pick['version']}")
            configure = ["./configure", "--enable-lib-only", "--disable-shared", "--enable-static"]
            configure.append(f"--prefix={self.prefix}")
            self.run(configure, tree)
            self.run(["make", f"-j{os.cpu_count() or 1}"], tree)
            self.run(["make", "install"], tree)
        library = self.prefix / "lib" / "libnghttp2.a"
        command = ["cc", "-O2", "-std=c11", "-o", str(self.binary), str(self.source / "peer.c")]
        command += [f"-I{self.prefix / 'include'}", str(library)]
        self.run(command, self.source)
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"cc left no executable {self.binary}")
        (self.root / "SHA256").write_text(f"{digest}\n")
        return self.run(["cc", "--version"], self.root).splitlines()[0]

    def prune(self) -> None:
        shutil.rmtree(self.prefix, ignore_errors=True)
