from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.parse
from pathlib import Path

from kit.remote import Remote

api = "https://api.adoptium.net/v3"
archs = {"x86_64": "x64", "aarch64": "aarch64"}


class Jdk(Remote):
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def binary(self) -> Path:
        return self.root / "bin" / "java"

    @classmethod
    def query(cls) -> str:
        return f"architecture={archs[cls.machine()]}&image_type=jdk&os=linux&jvm_impl=hotspot"

    @classmethod
    def latest(cls) -> str:
        lts = json.loads(cls.read(f"{api}/info/available_releases"))["most_recent_lts"]
        return str(json.loads(cls.read(f"{api}/assets/latest/{lts}/hotspot?{cls.query()}"))[0]["release_name"])

    def install(self, release: str) -> None:
        marker = self.root / "RELEASE_NAME"
        if marker.exists() and marker.read_text().strip() == release and os.access(self.binary, os.X_OK):
            return
        found = json.loads(self.read(f"{api}/assets/release_name/eclipse/{urllib.parse.quote(release)}?{self.query()}"))
        package = found["binaries"][0]["package"]
        self.root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root.parent) as work:
            tarball = Path(work, package["name"])
            digest = self.fetch(package["link"], tarball)
            if digest != package["checksum"]:
                raise RuntimeError(f"{package['name']}: sha256 {digest}, Adoptium lists {package['checksum']}")
            self.unpack(tarball, Path(work))
            tree = next(p for p in Path(work).iterdir() if p.is_dir())
            shutil.rmtree(self.root, ignore_errors=True)
            tree.rename(self.root)
        marker.write_text(f"{release}\n")
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"{release} unpacked no {self.binary}")

    def prune(self) -> None:
        for path in (self.root / "jmods", self.root / "lib" / "src.zip", self.root / "man", self.root / "demo"):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
