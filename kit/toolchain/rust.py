from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from kit.remote import Remote

channel = "https://static.rust-lang.org/dist/channel-rust-stable.toml"
rustup = "https://static.rust-lang.org/rustup/dist/{machine}-unknown-linux-gnu/rustup-init"


class Rust(Remote):
    def __init__(self, root: Path) -> None:
        self.root = root

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "RUSTUP_HOME": str(self.root / "rustup"),
            "CARGO_HOME": str(self.root / "cargo"),
            "PATH": f"{self.root / 'cargo' / 'bin'}:{os.environ.get('PATH', '')}",
        }

    @classmethod
    def latest(cls) -> str:
        return str(tomllib.loads(cls.read(channel).decode())["pkg"]["rust"]["version"].split()[0])

    def prune(self) -> None:
        for home in ("rustup", "cargo"):
            shutil.rmtree(self.root / home)

    def install(self, version: str) -> None:
        manager = self.root / "cargo" / "bin" / "rustup"
        if os.access(manager, os.X_OK):
            for step in (["toolchain", "install", version, "--profile", "minimal"], ["default", version]):
                subprocess.run([str(manager), *step], env=self.env(), check=True, stdout=subprocess.DEVNULL)
        else:
            url = rustup.format(machine=self.machine())
            expected = self.read(f"{url}.sha256").decode().split()[0]
            with tempfile.TemporaryDirectory() as work:
                init = Path(work, "rustup-init")
                digest = self.fetch(url, init)
                if digest != expected:
                    raise RuntimeError(f"rustup-init: sha256 {digest}, static.rust-lang.org lists {expected}")
                init.chmod(0o755)
                command = [str(init), "-y", "--no-modify-path", "--profile", "minimal", "--default-toolchain", version]
                subprocess.run(command, env=self.env(), check=True, stdout=subprocess.DEVNULL)
        said = self.said(["rustc", "--version"], env=self.env())
        if version not in said.split():
            raise RuntimeError(f"rustc --version says {said!r}, not {version}")
