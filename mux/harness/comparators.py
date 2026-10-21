from __future__ import annotations

import json
import re
from dataclasses import dataclass

from kit.remote import Remote

streams = ("bulk", "flows", "isolation", "pingpong", "loaded", "churn", "idle")
controls = ("flows", "isolation")  # see README.md "Comparators"


@dataclass(frozen=True)
class Comparator:
    name: str
    runtime: str
    package: str
    scenarios: tuple[str, ...] = streams
    modes: tuple[str, ...] = ()  # see README.md "Comparators"

    @property
    def impls(self) -> tuple[str, ...]:
        return self.modes or (self.name,)

    def latest(self) -> str:
        if self.runtime == "go":
            found = json.loads(Remote.read(f"https://proxy.golang.org/{self.package}/@latest"))
            return str(found["Version"])
        if self.runtime == "rust":
            found = json.loads(Remote.read(f"https://crates.io/api/v1/crates/{self.package}"))
            return str(found["crate"]["max_stable_version"])
        if self.runtime == "dotnet":
            found = json.loads(Remote.read(f"https://api.nuget.org/v3-flatcontainer/{self.package.lower()}/index.json"))
            return str([v for v in found["versions"] if "-" not in v][-1])
        if self.runtime == "c":
            found = json.loads(Remote.read(f"https://api.github.com/repos/{self.package}/releases/latest"))
            return str(found["tag_name"]).removeprefix("v")
        if self.runtime == "jvm":
            group, artifact = self.package.split(":")
            path = f"{group.replace('.', '/')}/{artifact}"
            meta = Remote.read(f"https://repo1.maven.org/maven2/{path}/maven-metadata.xml").decode()
            # see README.md "Build"
            final = [v for v in re.findall(r"<version>([^<]+)</version>", meta) if re.fullmatch(r"4(\.\d+)+\.Final", v)]
            return max(final, key=lambda v: tuple(int(x) for x in v.removesuffix(".Final").split(".")))
        if self.runtime == "node":
            return str(json.loads(Remote.read(f"https://registry.npmjs.org/{self.package}/latest"))["version"])
        raise NotImplementedError(f"{self.name}: no resolver for the {self.runtime} runtime")


comparators = (
    Comparator("hashicorp-yamux", "go", "github.com/hashicorp/yamux"),
    Comparator("go-yamux", "go", "github.com/libp2p/go-yamux/v5"),
    Comparator("smux", "go", "github.com/xtaci/smux"),
    Comparator("x-http2", "go", "golang.org/x/net"),
    Comparator("mplex", "go", "github.com/libp2p/go-mplex", controls),
    Comparator("yamux", "rust", "yamux"),
    Comparator("async-smux", "rust", "async_smux"),
    Comparator("h2", "rust", "h2"),
    Comparator("nerdbank", "dotnet", "Nerdbank.Streams"),
    Comparator("libp2p-yamux", "node", "@libp2p/yamux"),
    Comparator("nghttp2", "c", "nghttp2/nghttp2", modes=("nghttp2-core", "nghttp2-loopback")),
    Comparator("netty-http2", "jvm", "io.netty:netty-codec-http2"),
)
named = {c.name: c for c in comparators}
impls = {impl: c for c in comparators for impl in c.impls}
runtimes = sorted({c.runtime for c in comparators})
