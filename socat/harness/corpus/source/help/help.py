from __future__ import annotations

from collections.abc import Iterator

from harness.corpus.entry import Entry
from harness.corpus.form import Form
from harness.corpus.source.help.head import Head
from harness.corpus.source.help.option import Option

# see socat/README.md "Corpus"
hosts = [
    "TCP-CONNECT", "TCP-LISTEN", "UDP-CONNECT", "UDP-LISTEN", "UNIX-CONNECT", "UNIX-LISTEN",
    "OPEN", "GOPEN", "EXEC", "PTY", "STDIO", "VSOCK-CONNECT", "VSOCK-LISTEN",
]
forked = {"fork", "maxchildren"}


class Help:
    def __init__(self, text: str) -> None:
        self.heads: list[Head] = []
        self.options: list[Option] = []
        section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "address-head:":
                section = "head"
                continue
            if stripped in ("opts:", "opt:"):
                section = "opt"
                continue
            if not line.startswith("      "):
                continue
            words = line.split()
            if not words:
                continue
            first, rest = words[0], words[1:]
            alias = rest[-1] if rest and "alias" in rest else None
            fields = dict(w.split("=", 1) for w in rest if "=" in w)
            groups = tuple(g for g in fields.get("groups", "").split(",") if g)
            if section == "head":
                cut = min((i for i in (first.find(":"), first.find("[")) if i >= 0), default=len(first))
                self.heads.append(Head(first[:cut], first[cut:], groups, alias))
            elif section == "opt":
                self.options.append(Option(first, groups, fields.get("type", ""), alias))
        if not self.heads or not self.options:
            raise RuntimeError("socat -hhh: no address types or options parsed")

    def head(self, head: Head) -> Head:
        seen = {head.name}
        while head.alias and head.alias not in seen:
            target = next((h for h in self.heads if h.name == head.alias), None)
            if target is None:
                break
            seen.add(target.name)
            head = target
        return head

    def option(self, option: Option) -> Option:
        seen = {option.name}
        while option.alias and option.alias not in seen:
            target = next((o for o in self.options if o.name == option.alias), None)
            if target is None:
                break
            seen.add(target.name)
            option = target
        return option

    def hosts(self) -> list[Head]:
        own = [h for h in self.heads if h.alias is None]
        rank = {name: i for i, name in enumerate(hosts)}
        return sorted(own, key=lambda h: (rank.get(h.name, len(hosts)), "LISTEN" in h.name, h.name))

    def entries(self, origin: str) -> Iterator[Entry]:
        for head in self.heads:
            target = self.head(head)
            if head.name == "<filename>":
                form = "/tmp/f"
            elif head.name == "<num>":
                form = "3"
            else:
                form = f"{head.name}{Form.fill(target.signature)}"
            yield Entry(form, f"{origin}:type:{Form.family(target.name)}")
        ranked = self.hosts()
        for option in self.options:
            target = self.option(option)
            fits = [h for h in ranked if set(target.groups) & set(h.groups)]
            if Form.normal(target.name) in forked:
                fits = [h for h in fits if "LISTEN" in h.name] or fits
            if not fits:
                continue
            host = f"{fits[0].name}{Form.fill(fits[0].signature)}"
            value = Form.value(target.kind)
            text = f"{host},{option.name}={value}" if value is not None else f"{host},{option.name}"
            group = target.groups[0] if target.groups else "-"
            yield Entry(text, f"{origin}:option:{group}")
