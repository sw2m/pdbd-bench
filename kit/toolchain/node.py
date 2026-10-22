from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from kit.remote import Remote

dist = "https://nodejs.org/dist"
archs = {"x86_64": "x64", "aarch64": "arm64"}


class Node(Remote):
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def binary(self) -> Path:
        return self.root / "bin" / "node"

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "npm_config_cache": str(self.root.parent / "npm"),
            "npm_config_update_notifier": "false",
            "PATH": f"{self.binary.parent}:{os.environ.get('PATH', '')}",
        }

    @classmethod
    def latest(cls) -> str:
        return str(next(r for r in json.loads(cls.read(f"{dist}/index.json")) if r["lts"])["version"])

    def installed(self) -> str:
        if not os.access(self.binary, os.X_OK):
            return ""
        return self.said([str(self.binary), "--version"])

    def install(self, version: str) -> None:
        if self.installed() == version:
            return
        name = f"node-{version}-linux-{archs[self.machine()]}"
        sums = self.read(f"{dist}/{version}/SHASUMS256.txt").decode()
        listed = next((line.split()[0] for line in sums.splitlines() if line.endswith(f"  {name}.tar.xz")), None)
        if listed is None:
            raise RuntimeError(f"{dist}/{version}/SHASUMS256.txt lists no {name}.tar.xz")
        self.root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root.parent) as work:
            tarball = Path(work, f"{name}.tar.xz")
            digest = self.fetch(f"{dist}/{version}/{name}.tar.xz", tarball)
            if digest != listed:
                raise RuntimeError(f"{name}.tar.xz: sha256 {digest}, SHASUMS256.txt lists {listed}")
            self.unpack(tarball, Path(work))
            shutil.rmtree(self.root, ignore_errors=True)
            Path(work, name).rename(self.root)
        if self.installed() != version:
            raise RuntimeError(f"{self.binary} --version says {self.installed() or 'nothing'}, not {version}")

    def prune(self) -> None:
        built = (self.root / "lib" / "node_modules", self.root / "include", self.root / "share")
        for path in (*built, self.root.parent / "npm"):
            shutil.rmtree(path, ignore_errors=True)
        for tool in ("npm", "npx", "corepack"):
            (self.root / "bin" / tool).unlink(missing_ok=True)
