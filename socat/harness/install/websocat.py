from __future__ import annotations

import os
from pathlib import Path

from harness.install.oracle import Oracle

# a redirect to the release tag, which the unauthenticated API's 60 requests/hour don't limit
releases = "https://github.com/vi/websocat/releases/latest"
binaries = "https://github.com/vi/websocat/releases/download/{tag}/websocat.{machine}-unknown-linux-musl"
docs = "https://raw.githubusercontent.com/vi/websocat/{tag}/doc.md"


class Websocat(Oracle):
    name = "websocat"

    @property
    def binary(self) -> Path:
        return self.prefix / "bin" / "websocat"

    @property
    def doc(self) -> Path:
        return self.prefix / "doc.md"

    def version(self) -> tuple[str, str]:
        if self.pin:
            return self.pin, "pinned"
        landed = self.landed(releases)
        if "/releases/tag/" not in landed:
            raise RuntimeError(f"{releases} redirected to {landed}, not a release tag")
        return landed.rsplit("/", 1)[-1], "floating"

    def build(self, version: str) -> dict[str, str]:
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        digest = self.fetch(binaries.format(tag=version, machine=self.machine()), self.binary)
        self.binary.chmod(0o755)
        self.fetch(docs.format(tag=version), self.doc)
        return {"sha256": digest}

    def verify(self, version: str) -> None:
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"websocat {version} installed, but {self.binary} is not executable")
        said = self.said([str(self.binary), "--version"])
        if version.removeprefix("v") not in said.split():
            raise RuntimeError(f"{self.binary} --version says {said!r}, not {version}")
        if "Full list of address types" not in self.said([str(self.binary), "--help=full"]):
            raise RuntimeError(f"{self.binary} --help=full lists no address types: its help layout changed")
        if "Aliases:" not in self.doc.read_text(errors="replace"):
            raise RuntimeError(f"{self.doc} has no Aliases: entries: websocat's doc.md layout changed")
