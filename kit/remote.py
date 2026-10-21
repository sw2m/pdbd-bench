from __future__ import annotations

import hashlib
import platform
import subprocess
import tarfile
import urllib.request
from pathlib import Path

agent = {"User-Agent": "pdbd-bench (https://github.com/sw2m/pdbd-bench)"}


class Remote:
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
    def fetch(url: str, path: Path, algorithm: str = "sha256") -> str:
        digest = hashlib.new(algorithm)
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
                    base = target.parent if member.issym() else root
                    link = (base / member.linkname).resolve()
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
