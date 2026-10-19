from __future__ import annotations

from collections.abc import Iterator

from harness.corpus.entry import Entry
from harness.corpus.form import Form

# see socat/README.md "Corpus"
headings = [
    (("listen", "security"), "TCP-LISTEN:1"),
    (("file",), "OPEN:f"),
    (("exec",), "EXEC:true"),
    (("pty", "termios"), "PTY"),
    (("transfer",), "STDIO"),
    (("websocket",), "WS-CONNECT:127.0.0.1:1"),
    (("tls",), "OPENSSL:127.0.0.1:1"),
    (("proxy",), "PROXY:127.0.0.1:example.com:1"),
    (("posix",), "POSIXMQ-READ:/q"),
    (("tun",), "TUN"),
]
valued = ["time", "size", "limit", "count", "number", "second", "max", "path", "file", "name", "level", "mode", "="]


class Listing:
    def __init__(self, text: str) -> None:
        self.text = text

    @staticmethod
    def host(heading: str) -> str:
        return next((h for words, h in headings if any(w in heading for w in words)), "TCP-CONNECT:127.0.0.1:1")

    def entries(self) -> Iterator[Entry]:
        section = ""
        heading = ""
        signatures: dict[str, str] = {}
        counts = {"type": 0, "option": 0}
        for line in self.text.splitlines():
            if line == "Address types:":
                section = "type"
                continue
            if line == "Address options:":
                section = "option"
                continue
            if line and not line.startswith(" "):
                section = ""
            if not section:
                continue
            if line.startswith("  ") and not line.startswith("   "):
                heading = line.strip().lower()
                continue
            if not line.startswith("    "):
                continue
            words = line[4:].split(None, 1)
            first = words[0] if words else ""
            desc = words[1].strip().lower() if len(words) > 1 else ""
            if not first or (section == "option" and first.startswith("-")):
                continue
            if section == "type":
                cut = min((i for i in (first.find(":"), first.find("[")) if i >= 0), default=len(first))
                name, signature = first[:cut], first[cut:]
                for prefix in ("alias of ", "same as "):
                    if not signature and desc.startswith(prefix):
                        signature = signatures.get(desc[len(prefix):].split()[0].upper(), "")
                signatures[name] = signature
                counts["type"] += 1
                yield Entry(f"{name}{Form.fill(signature)}", f"oittaa:type:{Form.family(name)}")
            else:
                option = f"{first}=1" if any(w in desc for w in valued) else first
                counts["option"] += 1
                yield Entry(f"{self.host(heading)},{option}", f"oittaa:option:{heading}")
        if not counts["type"] or not counts["option"]:
            raise RuntimeError("oittaa -hhh: no address types or options parsed")
