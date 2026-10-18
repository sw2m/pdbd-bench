from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

releases = "https://api.github.com/repos/ppp-project/ppp/releases/latest"
# see https://download.samba.org/pub/ppp/
tarballs = "https://download.samba.org/pub/ppp/ppp-{version}.tar.gz"


class Build:
    def __init__(self, pin: str = "", prefix: Path = Path("/opt/pppd")) -> None:
        self.pin = pin
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

    def version(self) -> tuple[str, str]:
        if self.pin:
            return self.pin, "pinned"
        with urllib.request.urlopen(releases, timeout=60) as response:
            tag = str(json.load(response)["tag_name"])
        return tag.removeprefix("ppp-").removeprefix("v"), "floating"

    def run(self) -> None:
        version, mode = self.version()
        marker = self.prefix / "VERSION"
        if marker.exists() and marker.read_text().strip() == version:
            self.verify(version)
            return
        url = tarballs.format(version=version)
        with (
            tempfile.TemporaryDirectory() as build,
            urllib.request.urlopen(url, timeout=600) as response,
            tarfile.open(fileobj=response, mode="r|gz") as archive,
        ):
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
        marker.write_text(f"{version}\n")
        (self.prefix / "MODE").write_text(f"{mode}\n")
        print(f"pppd {version} ({mode}) built into {self.prefix}")
