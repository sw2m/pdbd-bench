from __future__ import annotations

import hashlib
import platform
import subprocess
import tarfile
import urllib.request
from pathlib import Path

agent = {"User-Agent": "pdbd-bench (https://github.com/sw2m/pdbd-bench)"}


class Oracle:
    name = ""

    def __init__(self, pin: str = "", root: Path = Path("/opt/oracles")) -> None:
        self.pin = pin
        self.prefix = root / self.name

    def version(self) -> tuple[str, str]:
        raise NotImplementedError

    def build(self, version: str) -> dict[str, str]:
        raise NotImplementedError

    def verify(self, version: str) -> None:
        raise NotImplementedError

    def run(self) -> None:
        version, mode = self.version()
        marker = self.prefix / "VERSION"
        if marker.exists() and marker.read_text().strip() == version:
            self.verify(version)
            (self.prefix / "MODE").write_text(f"{mode}\n")
            return
        self.prefix.mkdir(parents=True, exist_ok=True)
        facts = self.build(version)
        self.verify(version)
        for key, value in {**facts, "mode": mode}.items():
            (self.prefix / key.upper()).write_text(f"{value}\n")
        marker.write_text(f"{version}\n")
        print(f"{self.name} {version} ({mode}) installed into {self.prefix}")

    def provenance(self) -> dict[str, str]:
        return {
            path.name.lower(): path.read_text().strip()
            for path in sorted(self.prefix.iterdir())
            if path.is_file() and path.name.isupper()
        }

    @staticmethod
    def machine() -> str:
        return platform.machine()

    @staticmethod
    def landed(url: str) -> str:
        with urllib.request.urlopen(urllib.request.Request(url, headers=agent), timeout=60) as r:
            return r.geturl()

    @staticmethod
    def read(url: str) -> bytes:
        with urllib.request.urlopen(urllib.request.Request(url, headers=agent), timeout=60) as r:
            data: bytes = r.read()
            return data

    @staticmethod
    def fetch(url: str, path: Path) -> str:
        digest = hashlib.sha256()
        request = urllib.request.Request(url, headers=agent)
        with urllib.request.urlopen(request, timeout=600) as response, path.open("wb") as file:
            while chunk := response.read(1 << 20):
                digest.update(chunk)
                file.write(chunk)
        return digest.hexdigest()

    @staticmethod
    def unpack(tarball: Path, into: Path) -> None:
        root = into.resolve()
        with tarfile.open(tarball) as archive:
            for member in archive.getmembers():
                target = (root / member.name).resolve()
                if not target.is_relative_to(root) or member.isdev():
                    raise RuntimeError(f"{tarball}: member {member.name!r} would land outside {root}")
                if member.issym() or member.islnk():
                    link = (target.parent / member.linkname).resolve() if member.issym() else (root / member.linkname).resolve()
                    if not link.is_relative_to(root):
                        raise RuntimeError(f"{tarball}: link {member.name!r} points outside {root}")
            archive.extractall(into)

    @staticmethod
    def said(
        command: list[str],
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        cwd: Path | None = None,
    ) -> str:
        done = subprocess.run(command, capture_output=True, text=True, env=env, input=stdin, cwd=cwd)
        return f"{done.stdout}{done.stderr}".strip()
