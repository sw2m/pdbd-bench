from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from harness.install.oracle import Oracle

crate = "https://crates.io/api/v1/crates/tocat-core"
rustup = "https://static.rust-lang.org/rustup/dist/{machine}-unknown-linux-gnu/rustup-init"


class Tocat(Oracle):
    name = "tocat"

    @property
    def binary(self) -> Path:
        return self.prefix / "bin" / "tocat"

    @property
    def schemes(self) -> Path:
        return self.prefix / "parse.rs"

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "RUSTUP_HOME": str(self.prefix / "rustup"),
            "CARGO_HOME": str(self.prefix / "cargo"),
            "PATH": f"{self.prefix / 'cargo' / 'bin'}:{os.environ.get('PATH', '')}",
        }

    def toolchain(self) -> None:
        if os.access(self.prefix / "cargo" / "bin" / "cargo", os.X_OK):
            return
        url = rustup.format(machine=self.machine())
        expected = self.read(f"{url}.sha256").decode().split()[0]
        with tempfile.TemporaryDirectory() as work:
            init = Path(work, "rustup-init")
            digest = self.fetch(url, init)
            if digest != expected:
                raise RuntimeError(f"rustup-init: sha256 {digest}, static.rust-lang.org lists {expected}")
            init.chmod(0o755)
            command = [str(init), "-y", "--no-modify-path", "--profile", "minimal", "--default-toolchain", "stable"]
            subprocess.run(command, env=self.env(), check=True, stdout=subprocess.DEVNULL)

    def version(self) -> tuple[str, str]:
        if self.pin:
            return self.pin, "pinned"
        found = json.loads(self.read(crate))["crate"]["max_stable_version"]
        return str(found), "floating"

    def build(self, version: str) -> dict[str, str]:
        self.toolchain()
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

    def verify(self, version: str) -> None:
        said = self.said([str(self.binary)], stdin='"tcp:127.0.0.1:1"\n')
        if said != '{"ok":true}':
            raise RuntimeError(f"{self.binary} answered {said!r} to tcp:127.0.0.1:1, which tocat parses")
        built = (self.prefix / "src" / "Cargo.toml").read_text()
        if f'tocat-core = "={version}"' not in built:
            raise RuntimeError(f"{self.binary} wasn't built against tocat-core {version}")
        if "match normalize(scheme)" not in self.schemes.read_text():
            raise RuntimeError(f"{self.schemes} has no scheme table: tocat's parser layout changed")
