from __future__ import annotations

from pathlib import Path

from kit.remote import Remote


class Oracle(Remote):
    name = ""
    keys: tuple[str, ...] = ("version", "mode")

    def __init__(self, root: Path = Path("/opt/oracles")) -> None:
        self.prefix = root / self.name

    @classmethod
    def latest(cls) -> str:
        raise NotImplementedError

    @classmethod
    def pick(cls, pin: str) -> dict[str, str]:
        if pin:
            return {"version": pin, "mode": "pinned"}
        return {"version": cls.latest(), "mode": "floating"}

    def build(self, pick: dict[str, str]) -> dict[str, str]:
        raise NotImplementedError

    def verify(self, version: str) -> None:
        raise NotImplementedError

    def prune(self) -> None:
        pass

    def run(self, pick: dict[str, str]) -> None:
        version, mode = pick["version"], pick["mode"]
        marker = self.prefix / "VERSION"
        if marker.exists() and marker.read_text().strip() == version:
            self.verify(version)
            (self.prefix / "MODE").write_text(f"{mode}\n")
            return
        self.prefix.mkdir(parents=True, exist_ok=True)
        facts = self.build(pick)
        self.verify(version)
        for key, value in {**facts, "mode": mode}.items():
            (self.prefix / key.upper()).write_text(f"{value}\n")
        self.prune()
        marker.write_text(f"{version}\n")
        print(f"{self.name} {version} ({mode}) installed into {self.prefix}")

    def provenance(self) -> dict[str, str]:
        return {
            path.name.lower(): path.read_text().strip()
            for path in sorted(self.prefix.iterdir())
            if path.is_file() and path.name.isupper()
        }
