from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from harness.install.oracle import Oracle

module = "github.com/oittaa/socat"
toolchains = "https://go.dev/dl/?mode=json"
archs = {"x86_64": "amd64", "aarch64": "arm64"}


class Oittaa(Oracle):
    name = "oittaa"

    @property
    def binary(self) -> Path:
        return self.prefix / "bin" / "socat"

    @property
    def walker(self) -> Path:
        return self.prefix / "bin" / "walker"

    @property
    def go(self) -> Path:
        return self.prefix / "go" / "bin" / "go"

    @property
    def source(self) -> Path:
        return Path(__file__).resolve().parents[2] / "oittaa"

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "GOROOT": str(self.prefix / "go"),
            "GOPATH": str(self.prefix / "gopath"),
            "GOBIN": str(self.prefix / "bin"),
            "GOCACHE": str(self.prefix / "cache"),
            "GOTOOLCHAIN": "local",
            "PATH": f"{self.prefix / 'go' / 'bin'}:{os.environ.get('PATH', '')}",
        }

    def toolchain(self) -> None:
        if os.access(self.go, os.X_OK):
            return
        stable = next(r for r in json.loads(self.read(toolchains)) if r["stable"])
        arch = archs[self.machine()]
        file = next(
            f for f in stable["files"] if f["os"] == "linux" and f["arch"] == arch and f["kind"] == "archive"
        )
        with tempfile.TemporaryDirectory() as work:
            tarball = Path(work, file["filename"])
            digest = self.fetch(f"https://go.dev/dl/{file['filename']}", tarball)
            if digest != file["sha256"]:
                raise RuntimeError(f"{file['filename']}: sha256 {digest}, go.dev lists {file['sha256']}")
            self.prefix.mkdir(parents=True, exist_ok=True)
            self.unpack(tarball, self.prefix)

    def download(self, version: str) -> dict[str, str]:
        said = self.said(
            [str(self.go), "mod", "download", "-json", f"{module}@{version}"], env=self.env(), cwd=self.source
        )
        found: dict[str, str] = json.loads(said)
        if "Error" in found:
            raise RuntimeError(f"go mod download {module}@{version}: {found['Error']}")
        return found

    def version(self) -> tuple[str, str]:
        self.toolchain()
        if self.pin:
            return self.pin, "pinned"
        return self.download("latest")["Version"], "floating"

    def build(self, version: str) -> dict[str, str]:
        found = self.download(version)
        if not list(Path(found["Dir"], "internal", "parse").glob("*_test.go")):
            raise RuntimeError(f"{module}@{version} has no internal/parse/*_test.go: its layout changed")
        said = self.said([str(self.go), "install", f"{module}/cmd/socat@{version}"], env=self.env())
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"go install {module}/cmd/socat@{version} built nothing: {said[-400:]}")
        said = self.said([str(self.go), "build", "-o", str(self.walker), "."], env=self.env(), cwd=self.source)
        if not os.access(self.walker, os.X_OK):
            raise RuntimeError(f"the oittaa test walker didn't build: {said[-400:]}")
        return {"source": found["Dir"], "toolchain": self.said([str(self.go), "version"], env=self.env())}

    def verify(self, version: str) -> None:
        if "Address types:" not in self.said([str(self.binary), "-hhh"]):
            raise RuntimeError(f"{self.binary} -hhh lists no address types: oittaa's help layout changed")
        if not os.access(self.walker, os.X_OK):
            raise RuntimeError(f"{self.walker} is not executable")
        built = self.said([str(self.go), "version", "-m", str(self.binary)], env=self.env())
        if f"\tmod\t{module}\t{version}\t" not in built:
            raise RuntimeError(f"{self.binary} wasn't built from {module} {version}: {built[:300]!r}")
