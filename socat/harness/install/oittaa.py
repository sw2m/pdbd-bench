from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from harness.install.oracle import Oracle
from kit.toolchain import Go

module = "github.com/oittaa/socat"
proxy = f"https://proxy.golang.org/{module}/@latest"  # see https://go.dev/ref/mod#goproxy-protocol


class Oittaa(Oracle):
    name = "oittaa"
    keys = ("version", "mode", "go")

    @property
    def binary(self) -> Path:
        return self.prefix / "bin" / "socat"

    @property
    def walker(self) -> Path:
        return self.prefix / "bin" / "walker"

    @property
    def toolchain(self) -> Go:
        return Go(self.prefix / "go")

    @property
    def go(self) -> Path:
        return self.toolchain.binary

    @property
    def source(self) -> Path:
        return Path(__file__).resolve().parents[2] / "oittaa"

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "GOROOT": str(self.toolchain.root),
            "GOPATH": str(self.prefix / "gopath"),
            "GOBIN": str(self.prefix / "bin"),
            "GOCACHE": str(self.prefix / "cache"),
            "GOTOOLCHAIN": "local",
            "PATH": f"{self.go.parent}:{os.environ.get('PATH', '')}",
        }

    def download(self, version: str) -> dict[str, str]:
        said = self.said(
            [str(self.go), "mod", "download", "-json", f"{module}@{version}"], env=self.env(), cwd=self.source
        )
        found: dict[str, str] = json.loads(said)
        if "Error" in found:
            raise RuntimeError(f"go mod download {module}@{version}: {found['Error']}")
        return found

    @classmethod
    def latest(cls) -> str:
        return str(json.loads(cls.read(proxy))["Version"])

    @classmethod
    def pick(cls, pin: str) -> dict[str, str]:
        return {**super().pick(pin), "go": Go.latest()}

    def build(self, pick: dict[str, str]) -> dict[str, str]:
        version = pick["version"]
        self.toolchain.install(pick["go"])
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

    def prune(self) -> None:
        shutil.rmtree(self.prefix / "cache")
        shutil.rmtree(self.prefix / "gopath" / "pkg" / "mod" / "cache")
        self.toolchain.prune()

    def verify(self, version: str) -> None:
        if "Address types:" not in self.said([str(self.binary), "-hhh"]):
            raise RuntimeError(f"{self.binary} -hhh lists no address types: oittaa's help layout changed")
        if not os.access(self.walker, os.X_OK):
            raise RuntimeError(f"{self.walker} is not executable")
        built = self.said([str(self.go), "version", "-m", str(self.binary)], env=self.env())
        if f"\tmod\t{module}\t{version}\t" not in built:
            raise RuntimeError(f"{self.binary} wasn't built from {module} {version}: {built[:300]!r}")
