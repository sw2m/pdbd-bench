from __future__ import annotations

from collections.abc import Iterator

from harness.corpus.entry import Entry

# see socat/README.md "Corpus"
bodies = [
    (("exec", "system"), "true"),
    (("unix", "uds", "seqp"), "/tmp/s"),
    (("file", "open", "pipe", "fifo"), "f"),
    (("tty", "serial"), "/dev/ttyS0"),
    (("proxy", "socks"), "127.0.0.1:1:example.com:2"),
    (("ws", "websocket"), "127.0.0.1:1/x"),
    (("tcp", "udp", "listen", "connect", "tls", "ssl", "noise"), "127.0.0.1:1"),
]


class Schemes:
    def __init__(self, source: str) -> None:
        self.source = source

    @staticmethod
    def body(name: str) -> str:
        return next((b for words, b in bodies if any(w in name for w in words)), "")

    def names(self) -> list[str]:
        start = self.source.find("match normalize(scheme)")
        if start < 0:
            raise RuntimeError("tocat: no scheme table in endpoint/parse.rs")
        block = self.source[start:]
        end = block.find("other =>")
        if end < 0:
            raise RuntimeError("tocat: no end to the scheme table in endpoint/parse.rs")
        names = []
        for line in block[:end].splitlines()[1:]:
            t = line.lstrip()
            if t.startswith(('"', "|")):
                names += t.split("=>")[0].split('"')[1::2]
        if not names:
            raise RuntimeError("tocat: no schemes in its scheme table")
        return names

    def entries(self) -> Iterator[Entry]:
        yield Entry("-", "tocat:scheme")
        for name in self.names():
            yield Entry(f"{name}:{self.body(name)}", "tocat:scheme")
