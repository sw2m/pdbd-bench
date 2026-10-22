from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from kit.remote import Remote

index = "https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/releases-index.json"
rids = {"x86_64": "linux-x64", "aarch64": "linux-arm64"}


class Dotnet(Remote):
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def binary(self) -> Path:
        return self.root / "dotnet"

    @property
    def rid(self) -> str:
        return rids[self.machine()]

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "DOTNET_ROOT": str(self.root),
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
            "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
            "NUGET_PACKAGES": str(self.root.parent / "nuget"),
            "PATH": f"{self.root}:{os.environ.get('PATH', '')}",
        }

    @classmethod
    def latest(cls) -> str:
        channels = json.loads(cls.read(index))["releases-index"]
        return str(next(c for c in channels if c["support-phase"] == "active")["latest-sdk"])

    def installed(self) -> str:
        if not os.access(self.binary, os.X_OK):
            return ""
        return self.said([str(self.binary), "--version"], env=self.env())

    def install(self, version: str) -> None:
        if self.installed() == version:
            return
        channel = ".".join(version.split(".")[:2])
        entry = next(c for c in json.loads(self.read(index))["releases-index"] if c["channel-version"] == channel)
        releases = json.loads(self.read(entry["releases.json"]))["releases"]
        sdk = next((s for r in releases for s in r.get("sdks", []) if s["version"] == version), None)
        if sdk is None:
            raise RuntimeError(f"the .NET {channel} release metadata lists no SDK {version}")
        file = next(f for f in sdk["files"] if f["rid"] == self.rid and f["name"].endswith(".tar.gz"))
        self.root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root.parent) as work:
            tarball = Path(work, "sdk.tar.gz")
            digest = self.fetch(file["url"], tarball, "sha512")
            if digest != file["hash"].lower():
                raise RuntimeError(f"{file['url']}: sha512 {digest}, the release metadata lists {file['hash']}")
            shutil.rmtree(self.root, ignore_errors=True)
            self.root.mkdir()
            self.unpack(tarball, self.root)
        if self.installed() != version:
            raise RuntimeError(f"{self.binary} --version says {self.installed() or 'nothing'}, not {version}")

    def prune(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.root.parent / "nuget", ignore_errors=True)
