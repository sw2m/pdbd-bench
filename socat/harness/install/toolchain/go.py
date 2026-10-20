from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from harness.install.remote import Remote

stable = "https://go.dev/dl/?mode=json"
releases = "https://go.dev/dl/?mode=json&include=all"
archs = {"x86_64": "amd64", "aarch64": "arm64"}


class Go(Remote):
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def binary(self) -> Path:
        return self.root / "bin" / "go"

    @classmethod
    def latest(cls) -> str:
        return str(next(r for r in json.loads(cls.read(stable)) if r["stable"])["version"])

    def installed(self) -> str:
        marker = self.root / "VERSION"
        if not os.access(self.binary, os.X_OK) or not marker.exists():
            return ""
        return marker.read_text().split()[0]

    def prune(self) -> None:
        for path in self.root.iterdir():
            if path.is_dir() and path != self.binary.parent:
                shutil.rmtree(path)
            elif not path.is_dir():
                path.unlink()

    def install(self, version: str) -> None:
        if self.installed() == version:
            return
        release = next((r for r in json.loads(self.read(releases)) if r["version"] == version), None)
        if release is None:
            raise RuntimeError(f"go.dev lists no {version}")
        arch = archs[self.machine()]
        file = next(
            f for f in release["files"] if f["os"] == "linux" and f["arch"] == arch and f["kind"] == "archive"
        )
        self.root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root.parent) as work:
            tarball = Path(work, file["filename"])
            digest = self.fetch(f"https://go.dev/dl/{file['filename']}", tarball)
            if digest != file["sha256"]:
                raise RuntimeError(f"{file['filename']}: sha256 {digest}, go.dev lists {file['sha256']}")
            self.unpack(tarball, Path(work))
            shutil.rmtree(self.root, ignore_errors=True)
            Path(work, "go").rename(self.root)
        if self.installed() != version:
            raise RuntimeError(f"{self.root} holds {self.installed() or 'nothing'}, not {version}")
