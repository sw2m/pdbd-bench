from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from harness.install.oracle import Oracle

# see socat/README.md "Oracles track upstream"
downloads = "http://www.dest-unreach.org/socat/download/"


class Socat(Oracle):
    name = "socat"

    @property
    def binary(self) -> Path:
        return self.prefix / "bin" / "socat"

    @classmethod
    def latest(cls) -> str:
        index = cls.read(downloads).decode(errors="replace")
        found = set(re.findall(r"socat-(\d+(?:\.\d+)+)\.tar\.gz", index))
        if not found:
            raise RuntimeError(f"{downloads} lists no socat-<version>.tar.gz")
        return max(found, key=lambda v: tuple(int(p) for p in v.split(".")))

    def build(self, pick: dict[str, str]) -> dict[str, str]:
        version = pick["version"]
        with tempfile.TemporaryDirectory() as work:
            tarball = Path(work, "socat.tar.gz")
            digest = self.fetch(f"{downloads}socat-{version}.tar.gz", tarball)
            self.unpack(tarball, Path(work))
            source = Path(work, f"socat-{version}")
            for step in (
                ["./configure", f"--prefix={self.prefix}"],
                ["make", "-j", str(os.cpu_count() or 1)],
                ["make", "install"],
            ):
                subprocess.run(step, cwd=source, check=True, stdout=subprocess.DEVNULL)
        return {"sha256": digest, "toolchain": self.said(["cc", "--version"]).splitlines()[0]}

    def verify(self, version: str) -> None:
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"socat {version} installed, but {self.binary} is not executable")
        said = self.said([str(self.binary), "-V"])
        if f"socat version {version} " not in said:
            raise RuntimeError(f"{self.binary} -V doesn't say socat version {version}: {said[:200]!r}")
