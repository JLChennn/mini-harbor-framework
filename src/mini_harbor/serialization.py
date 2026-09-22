"""JSON 持久化工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    """以稳定、可读的格式写 JSON，并自动创建父目录。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_json_line(path: Path, event: dict[str, Any]) -> None:
    """将生命周期事件追加为 JSON Lines，便于边运行边观察。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")

