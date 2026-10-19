from __future__ import annotations

from collections.abc import Iterator

from harness.corpus.entry import Entry

stops = "|&;><"


class Websocat:
    def __init__(self, help: str, doc: str) -> None:
        self.help = help
        self.doc = doc

    @staticmethod
    def words(command: str) -> list[str]:
        out: list[str] = []
        current: list[str] = []
        quote = ""
        started = False
        for c in command:
            if not quote and c in "'\"":
                quote, started = c, True
            elif quote and c == quote:
                quote = ""
            elif not quote and c.isspace():
                if started:
                    out.append("".join(current))
                current, started = [], False
            elif not quote and c in stops:
                break
            else:
                current.append(c)
                started = True
        if started:
            out.append("".join(current))
        return out

    def examples(self) -> list[str]:
        out = []
        for line in self.doc.splitlines():
            command = line.lstrip().removeprefix("websocat ")
            if command == line.lstrip() or not line.startswith("    "):
                continue
            out += [w for w in self.words(command) if (not w.startswith("-") or w == "-") and (":" in w or w == "-")]
        return out

    def aliases(self) -> list[tuple[str, list[str]]]:
        out = []
        name = None
        for line in self.doc.splitlines():
            if line.startswith("### `"):
                name = line[5:].split("`")[0]
            elif name is not None and line.startswith("Aliases:"):
                out.append((name, line.split("`")[1::2]))
        return out

    @staticmethod
    def guess(name: str, desc: str, section: str) -> str:
        if section == "overlay":
            return f"{name}tcp:127.0.0.1:1"
        if name.endswith("://"):
            return f"{name}127.0.0.1/"
        for words, arg in (
            (("abstract",), "name"),
            (("unix",), "/tmp/s"),
            (("port", "socket address"), "127.0.0.1:1"),
            (("file", "path"), "/tmp/f"),
            (("command", "program"), "true"),
        ):
            if any(w in desc for w in words):
                return f"{name}{arg}"
        return name

    def entries(self) -> Iterator[Entry]:
        aliases = self.aliases()
        names = [l[1:].split("\t")[0].strip() for l in self.help.splitlines() if l.startswith("\t")]
        known = [n for n in names if n] + [a for pair in aliases for a in pair[1]]
        examples = [e for e in self.examples() if e == "-" or any(n != "-" and e.startswith(n) for n in known)]
        section = ""
        found = 0
        for line in self.help.splitlines():
            if line.startswith("Full list of address types"):
                section = "type"
                continue
            if line.startswith("Full list of overlays"):
                section = "overlay"
                continue
            if not line.startswith("\t") or not section:
                continue
            cells = line[1:].split("\t", 1)
            name, desc = cells[0].strip(), cells[1] if len(cells) > 1 else ""
            if not name:
                continue
            form = next(
                (e for e in examples if e.startswith(name) and len(e) > len(name)),
                self.guess(name, desc.lower(), section),
            )
            found += 1
            yield Entry(form, f"websocat:{section}")
            for alias in (a for n, more in aliases if n == name for a in more):
                yield Entry(f"{alias}{form[len(name):]}", f"websocat:{section}")
        if not found:
            raise RuntimeError("websocat --help=full: no address types or overlays parsed")
        for example in examples:
            yield Entry(example, "websocat:example")
