from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# a redirect to the release tag, which the unauthenticated API's 60 requests/hour don't limit
releases = "https://github.com/ppp-project/ppp/releases/latest"
# see https://download.samba.org/pub/ppp/
tarballs = "https://download.samba.org/pub/ppp/ppp-{version}.tar.gz"


class Build:
    name = "pppd"

    def __init__(self, prefix: Path = Path("/opt/pppd")) -> None:
        self.prefix = prefix

    @property
    def binary(self) -> Path:
        return self.prefix / "sbin" / "pppd"

    def verify(self, version: str) -> None:
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(
                f"pppd {version} installed, but {self.binary} is not an executable: "
                "upstream's install layout changed"
            )
        done = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True)
        said = (done.stdout + done.stderr).strip()
        if version not in said.split():
            raise RuntimeError(f"{self.binary} --version says {said!r}, not pppd {version}")

    @staticmethod
    def latest() -> str:
        with urllib.request.urlopen(releases, timeout=60) as response:
            landed = response.geturl()
        if "/releases/tag/" not in landed:
            raise RuntimeError(f"{releases} redirected to {landed}, not a release tag")
        tag = landed.rsplit("/", 1)[-1]
        return tag.removeprefix("ppp-").removeprefix("v")

    @classmethod
    def pick(cls, pin: str) -> dict[str, str]:
        if pin:
            return {"version": pin, "mode": "pinned"}
        return {"version": cls.latest(), "mode": "floating"}

    def run(self, pick: dict[str, str]) -> None:
        version, mode = pick["version"], pick["mode"]
        marker = self.prefix / "VERSION"
        if marker.exists() and marker.read_text().strip() == version:
            self.verify(version)
            (self.prefix / "MODE").write_text(f"{mode}\n")
            return
        url = tarballs.format(version=version)
        digest = hashlib.sha256()
        with tempfile.TemporaryDirectory() as build:
            tarball = Path(build, "ppp.tar.gz")
            with urllib.request.urlopen(url, timeout=600) as response, tarball.open("wb") as file:
                while chunk := response.read(1 << 20):
                    digest.update(chunk)
                    file.write(chunk)
            with tarfile.open(tarball, mode="r:gz") as archive:
                if hasattr(tarfile, "data_filter"):
                    archive.extractall(build, filter="data")
                else:
                    archive.extractall(build)
            source = Path(build, f"ppp-{version}")
            for step in (
                ["./configure", f"--prefix={self.prefix}", "--sysconfdir=/etc"],
                ["make", "-j", str(os.cpu_count() or 1)],
                ["make", "install"],
            ):
                subprocess.run(step, cwd=source, check=True, stdout=subprocess.DEVNULL)
        self.verify(version)
        cc = subprocess.run(["cc", "--version"], capture_output=True, text=True, check=True)
        (self.prefix / "TOOLCHAIN").write_text(cc.stdout.splitlines()[0] + "\n")
        (self.prefix / "SHA256").write_text(f"{digest.hexdigest()}\n")
        marker.write_text(f"{version}\n")
        (self.prefix / "MODE").write_text(f"{mode}\n")
        print(f"pppd {version} ({mode}) built into {self.prefix}")
