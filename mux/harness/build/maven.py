from __future__ import annotations

import hashlib
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from harness.build.builder import Builder
from harness.comparators import Comparator
from kit.toolchain import Jdk

central = "https://repo1.maven.org/maven2"
pom = "{http://maven.apache.org/POM/4.0.0}"


class Maven(Builder):
    runtime = "jvm"

    def __init__(self, root: Path, source: Path) -> None:
        self.root = root
        self.source = source
        self.toolchain = Jdk(root / "toolchain")
        self.lib = root / "lib"
        self.classes = root / "classes"

    @property
    def binary(self) -> Path:
        return self.root / "peer"

    # see README.md "Build"
    @classmethod
    def closure(cls, group: str, artifact: str, version: str) -> list[str]:
        seen: list[str] = []
        todo = [artifact]
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.append(name)
            path = f"{central}/{group.replace('.', '/')}/{name}/{version}/{name}-{version}.pom"
            root = ElementTree.fromstring(cls.read(path))
            for dep in root.iter(f"{pom}dependency"):
                own = {"${project.groupId}": group, "${project.version}": version}  # netty's POMs name their own group
                texts = {child.tag.removeprefix(pom): (child.text or "").strip() for child in dep}
                found = {tag: own.get(text, text) for tag, text in texts.items()}
                if found.get("groupId") != group or found.get("optional") == "true":
                    continue
                if found.get("scope", "compile") not in ("compile", "runtime") or found.get("type", "jar") != "jar":
                    continue
                if found.get("classifier"):
                    continue
                todo.append(found["artifactId"])
        return sorted(seen)

    def jar(self, group: str, name: str, version: str) -> Path:
        base = f"{central}/{group.replace('.', '/')}/{name}/{version}/{name}-{version}"
        target = self.lib / f"{name}-{version}.jar"
        listed = self.read(f"{base}.jar.sha1").decode().split()[0]
        self.fetch(f"{base}.jar", target)
        digest = hashlib.sha1(target.read_bytes()).hexdigest()
        if digest != listed:
            raise RuntimeError(f"{target.name}: sha1 {digest}, Maven Central lists {listed}")
        return target

    def build(self, version: str, picks: dict[Comparator, dict[str, str]]) -> str:
        (comparator, pick), = picks.items()
        group, artifact = comparator.package.split(":")
        self.toolchain.install(version)
        shutil.rmtree(self.lib, ignore_errors=True)
        shutil.rmtree(self.classes, ignore_errors=True)
        self.lib.mkdir(parents=True)
        jars = [self.jar(group, name, pick["version"]) for name in self.closure(group, artifact, pick["version"])]
        classpath = ":".join(map(str, jars))
        javac = self.toolchain.root / "bin" / "javac"
        command = [str(javac), "-d", str(self.classes), "-cp", classpath, str(self.source / "Peer.java")]
        done = subprocess.run(command, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"javac: exit {done.returncode}: {(done.stdout + done.stderr)[-600:]}")
        java = self.toolchain.root / "bin" / "java"
        # see README.md "Scenarios"
        shrink = "-XX:+UseSerialGC -XX:MinHeapFreeRatio=0 -XX:MaxHeapFreeRatio=0"
        self.binary.write_text(
            f'#!/bin/sh\nflags=\n[ "$2" = idle ] && flags="{shrink}"\n'
            f'exec {java} --enable-native-access=ALL-UNNAMED $flags -cp {self.classes}:{classpath} Peer "$@"\n'
        )
        self.binary.chmod(0o755)
        return self.said([str(java), "-version"]).splitlines()[0]

    def prune(self) -> None:
        self.toolchain.prune()
