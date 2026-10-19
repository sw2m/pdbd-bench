from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class Batch:
    def __init__(self, binary: Path) -> None:
        self.binary = binary

    def answers(self, texts: list[str]) -> list[dict[str, Any]]:
        stdin = "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in texts)
        done = subprocess.run([str(self.binary)], input=stdin, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"{self.binary} exited {done.returncode}: {done.stderr[-400:]}")
        lines = done.stdout.splitlines()
        if len(lines) != len(texts):
            raise RuntimeError(f"{self.binary} answered {len(lines)} lines for {len(texts)} inputs")
        answers = []
        for number, line in enumerate(lines, start=1):
            answer = json.loads(line)
            if not isinstance(answer, dict) or not isinstance(answer.get("ok"), bool):
                raise RuntimeError(f"{self.binary} line {number}: {line!r} has no boolean ok")
            answers.append(answer)
        return answers
