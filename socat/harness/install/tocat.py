from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from harness.install.oracle import Oracle
from kit.toolchain import Rust

crate = "https://crates.io/api/v1/crates/tocat-core"


class Tocat(Oracle):
    name = "tocat"
    keys = ("version", "mode", "rust")

    @property
    def binary(self) -> Path:
        return self.prefix / "bin" / "tocat"

    @property
    def schemes(self) -> Path:
        return self.prefix / "parse.rs"

    @property
    def toolchain(self) -> Rust:
        return Rust(self.prefix)

    def env(self) -> dict[str, str]:
        return self.toolchain.env()

    @classmethod
    def latest(cls) -> str:
        return str(json.loads(cls.read(crate))["crate"]["max_stable_version"])

    @classmethod
    def pick(cls, pin: str) -> dict[str, str]:
        return {**super().pick(pin), "rust": Rust.latest()}

    def build(self, pick: dict[str, str]) -> dict[str, str]:
        version = pick["version"]
        self.toolchain.install(pick["rust"])
        work = self.prefix / "src"
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(Path(__file__).resolve().parents[2] / "tocat", work)
        manifest = work / "Cargo.toml"
        floating = manifest.read_text()
        pinned = floating.replace('tocat-core = "*"', f'tocat-core = "={version}"')
        if pinned == floating:
            raise RuntimeError(f"{manifest} has no tocat-core = \"*\" line to pin to {version}")
        manifest.write_text(pinned)
        subprocess.run(["cargo", "build", "-q", "--release"], cwd=work, env=self.env(), check=True)
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(work / "target" / "release" / "tocat", self.binary)
        meta = json.loads(
            self.said(["cargo", "metadata", "-q", "--format-version", "1"], env=self.env(), cwd=work)
        )
        package = next(p for p in meta["packages"] if p["name"] == "tocat-core")
        source = Path(package["manifest_path"]).parent / "src" / "endpoint" / "parse.rs"
        if not source.exists():
            raise RuntimeError(f"tocat-core {version} has no src/endpoint/parse.rs: its layout changed")
        shutil.copy2(source, self.schemes)
        return {"toolchain": self.said(["rustc", "--version"], env=self.env())}

    def prune(self) -> None:
        shutil.rmtree(self.prefix / "src" / "target")
        self.toolchain.prune()

    def verify(self, version: str) -> None:
        said = self.said([str(self.binary)], stdin='"tcp:127.0.0.1:1"\n')
        if said != '{"ok":true}':
            raise RuntimeError(f"{self.binary} answered {said!r} to tcp:127.0.0.1:1, which tocat parses")
        built = (self.prefix / "src" / "Cargo.toml").read_text()
        if f'tocat-core = "={version}"' not in built:
            raise RuntimeError(f"{self.binary} wasn't built against tocat-core {version}")
        if "match normalize(scheme)" not in self.schemes.read_text():
            raise RuntimeError(f"{self.schemes} has no scheme table: tocat's parser layout changed")
