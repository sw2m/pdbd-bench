from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from harness.build.builder import Builder
from harness.comparators import Comparator

releases = "https://github.com/{package}/releases/download/v{version}"
archives = "https://github.com/{package}/archive/{version}.tar.gz"
api = "https://api.github.com/repos/{package}"
# see README.md "Build": what an ngtcp2-family configure detects on Debian
detected = (
    "-DHAVE_ARPA_INET_H=1",
    "-DHAVE_NETINET_IN_H=1",
    "-DHAVE_UNISTD_H=1",
    "-DHAVE_ENDIAN_H=1",
    "-DHAVE_BYTESWAP_H=1",
    "-DHAVE_DECL_BE64TOH=1",
    "-DHAVE_DECL_BSWAP_64=1",
    "-DHAVE_EXPLICIT_BZERO=1",
)


class Tree:
    @staticmethod
    def blob(data: bytes) -> str:
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

    @classmethod
    def hash(cls, path: Path) -> str:
        entries = []
        for child in path.iterdir():
            if child.is_symlink():
                mode, sha = b"120000", cls.blob(os.readlink(child).encode())
            elif child.is_dir():
                mode, sha = b"40000", cls.hash(child)
            else:
                mode = b"100755" if os.access(child, os.X_OK) else b"100644"
                sha = cls.blob(child.read_bytes())
            entries.append((child.name.encode(), mode, sha))
        entries.sort(key=lambda e: e[0] + (b"/" if e[1] == b"40000" else b""))
        body = b"".join(mode + b" " + name + b"\0" + bytes.fromhex(sha) for name, mode, sha in entries)
        return hashlib.sha1(b"tree %d\0" % len(body) + body).hexdigest()


class Make(Builder):
    runtime = "c"

    def __init__(self, root: Path, source: Path) -> None:
        self.root = root
        self.source = source

    @property
    def binary(self) -> Path:
        return self.root / "peer"

    def prefix(self, comparator: Comparator) -> Path:
        return self.root / comparator.name

    def run(self, command: list[str], cwd: Path) -> str:
        done = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
        said = f"{done.stdout}{done.stderr}".strip()
        if done.returncode != 0:
            raise RuntimeError(f"{' '.join(command[:2])}: exit {done.returncode}: {said[-600:]}")
        return said

    def release(self, comparator: Comparator, version: str, work: Path) -> str:
        release = releases.format(package=comparator.package, version=version)
        name = f"{comparator.name}-{version}.tar.xz"
        sums = self.read(f"{release}/checksums.txt").decode()
        listed = next((line.split()[0] for line in sums.splitlines() if line.endswith(f"  {name}")), None)
        if listed is None:
            raise RuntimeError(f"{release}/checksums.txt lists no {name}")
        tarball = work / name
        digest = self.fetch(f"{release}/{name}", tarball)
        if digest != listed:
            raise RuntimeError(f"{name}: sha256 {digest}, checksums.txt lists {listed}")
        self.unpack(tarball, work)
        tree = work / f"{comparator.name}-{version}"
        configure = ["./configure", "--enable-lib-only", "--disable-shared", "--enable-static"]
        configure.append(f"--prefix={self.prefix(comparator)}")
        self.run(configure, tree)
        self.run(["make", f"-j{os.cpu_count() or 1}"], tree)
        self.run(["make", "install"], tree)
        return f"sha256 {digest}"

    def commit(self, comparator: Comparator, version: str, work: Path) -> str:
        base = api.format(package=comparator.package)
        root = json.loads(self.read(f"{base}/git/commits/{version}"))["tree"]["sha"]
        listing = json.loads(self.read(f"{base}/git/trees/{root}"))["tree"]
        expected = next((e["sha"] for e in listing if e["path"] == "lib" and e["type"] == "tree"), None)
        if expected is None:
            raise RuntimeError(f"{comparator.package}@{version} has no lib/ tree")
        tarball = work / f"{comparator.name}.tar.gz"
        self.fetch(archives.format(package=comparator.package, version=version), tarball)
        self.unpack(tarball, work)
        lib = work / f"{comparator.name}-{version}" / "lib"
        found = Tree.hash(lib)
        if found != expected:
            raise RuntimeError(f"{comparator.package}@{version}: lib/ is tree {found}, the commit says {expected}")
        prefix, macro = self.prefix(comparator), comparator.name.upper()
        headers = prefix / "include" / comparator.name
        headers.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lib / "includes" / comparator.name / f"{comparator.name}.h", headers)
        template = (lib / "includes" / comparator.name / "version.h.in").read_text()
        (headers / "version.h").write_text(
            template.replace("@PACKAGE_VERSION@", version).replace("@PACKAGE_VERSION_NUM@", "0x000000")
        )
        objects = []
        for unit in sorted(lib.glob("*.c")):
            target = work / f"{unit.stem}.o"
            command = ["cc", "-O2", "-std=c11", "-D_GNU_SOURCE", f"-DBUILDING_{macro}", f"-D{macro}_STATICLIB", *detected]
            command += [f"-I{prefix / 'include'}", f"-I{lib}", "-c", str(unit), "-o", str(target)]
            self.run(command, work)
            objects.append(str(target))
        (prefix / "lib").mkdir(parents=True, exist_ok=True)
        self.run(["ar", "rcs", str(prefix / "lib" / f"lib{comparator.name}.a"), *objects], work)
        return f"tree {found}"

    def build(self, version: str, picks: dict[Comparator, dict[str, str]]) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        sources, command = [], ["cc", "-O2", "-std=c11", "-o", str(self.binary)]
        command += [str(self.source / "peer.c")]
        libraries = []
        for comparator, pick in picks.items():
            with tempfile.TemporaryDirectory(dir=self.root) as work:
                fetch = self.commit if comparator.track == "commit" else self.release
                sources.append(f"{comparator.name} {fetch(comparator, pick['version'], Path(work))}")
            command += [str(self.source / f"{comparator.name}.c"), f"-I{self.prefix(comparator) / 'include'}"]
            if comparator.track == "commit":
                command.append(f"-D{comparator.name.upper()}_STATICLIB")
            libraries.append(str(self.prefix(comparator) / "lib" / f"lib{comparator.name}.a"))
        self.run(command + libraries, self.source)
        if not os.access(self.binary, os.X_OK):
            raise RuntimeError(f"cc left no executable {self.binary}")
        (self.root / "SOURCES").write_text("".join(f"{line}\n" for line in sources))
        return self.run(["cc", "--version"], self.root).splitlines()[0]

    def prune(self) -> None:
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
