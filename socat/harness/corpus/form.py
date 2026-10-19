from __future__ import annotations

import re

samples = {
    "127.0.0.1": {
        "host", "target-host", "listen-host", "remote-address", "local-address", "ip-addr",
        "address", "proxy-server", "socks-server",
    },
    "1": {"port", "target-port", "listen-port", "socks-port", "domain", "type", "num"},
    "f": {"filename", "file", "lockfile", "logfile"},
    "true": {"command-line", "shell-command"},
    "2": {"cid"},
    "3": {"fdnum"},
    "255": {"protocol"},
    "lo": {"interface"},
    "/q": {"mqname"},
    "24": {"bits"},
}
values = {
    "x": {"STRING", "STRING-NULL", "GENERIC", "BIN", "IP4NAME"},
    "127.0.0.1": {"IP4SOCK", "STRUCT-IP_MREQN", "IP-MREQ-SOURCE"},
}


class Form:
    @staticmethod
    def sample(kind: str) -> str:
        return next((value for value, kinds in samples.items() if kind in kinds), "x")

    @classmethod
    def fill(cls, signature: str) -> str:
        depth = 0
        plain = []
        for c in signature:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
            elif depth == 0:
                plain.append(c)
        return re.sub(r"<([^>]*)>?", lambda m: cls.sample(m.group(1)), "".join(plain))

    @staticmethod
    def value(kind: str) -> str | None:
        def one(k: str) -> str:
            return next((value for value, kinds in values.items() if k in kinds), "1")

        if kind in ("BOOL", "CONST", ""):
            return None
        if kind == "INT[3]":
            return "1:1:1"
        return ":".join(one(k) for k in kind.split(":"))

    @staticmethod
    def family(name: str) -> str:
        root = name.split("-")[0].rstrip("0123456789")
        return root or name

    @staticmethod
    def normal(name: str) -> str:
        return name.replace("-", "").replace("_", "").lower()
