"""Task 目录的读取与校验。"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FileVerifierSpec:
    """文件断言型 Verifier 的任务配置。"""

    path: str
    expected_content: str


@dataclass(frozen=True, slots=True)
class Task:
    """一个可执行评测题目。

    目录约定：
    - instruction.md：交给 Agent 的任务描述；
    - task.toml：任务名、超时和评分规则；
    - environment/：可选的初始工作区文件。
    """

    path: Path
    name: str
    instruction: str
    agent_timeout_sec: float
    verifier_timeout_sec: float
    verifier: FileVerifierSpec

    @property
    def environment_dir(self) -> Path:
        return self.path / "environment"

    @classmethod
    def load(cls, path: Path | str) -> "Task":
        task_path = Path(path).resolve()
        config_path = task_path / "task.toml"
        instruction_path = task_path / "instruction.md"

        if not config_path.is_file():
            raise FileNotFoundError(f"Task 缺少配置文件：{config_path}")
        if not instruction_path.is_file():
            raise FileNotFoundError(f"Task 缺少指令文件：{instruction_path}")

        with config_path.open("rb") as stream:
            config: dict[str, Any] = tomllib.load(stream)

        try:
            task_name = str(config["task"]["name"])
            timeout_sec = float(config.get("agent", {}).get("timeout_sec", 30.0))
            verifier_config = config["verifier"]
            verifier_timeout_sec = float(verifier_config.get("timeout_sec", 30.0))
            verifier_type = verifier_config.get("type", "file")
            if verifier_type != "file":
                raise ValueError(f"教学版只支持 file verifier，收到：{verifier_type}")
            verifier = FileVerifierSpec(
                path=str(verifier_config["path"]),
                expected_content=str(verifier_config["expected_content"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"无法解析 Task 配置：{config_path}") from exc

        if timeout_sec <= 0:
            raise ValueError("agent.timeout_sec 必须大于 0。")
        if verifier_timeout_sec <= 0:
            raise ValueError("verifier.timeout_sec 必须大于 0。")

        instruction = instruction_path.read_text(encoding="utf-8").strip()
        if not instruction:
            raise ValueError("instruction.md 不能为空。")

        # 在加载阶段就校验路径，避免 Agent 或 Verifier 越出工作区。
        _validate_relative_path(verifier.path)

        return cls(
            path=task_path,
            name=task_name,
            instruction=instruction,
            agent_timeout_sec=timeout_sec,
            verifier_timeout_sec=verifier_timeout_sec,
            verifier=verifier,
        )

    def digest(self) -> str:
        """根据 Task 全部文件生成稳定digest，供 lock.json 固化输入。"""

        digest = hashlib.sha256()
        for file_path in sorted(path for path in self.path.rglob("*") if path.is_file()):
            relative = file_path.relative_to(self.path).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()


def _validate_relative_path(path: str) -> None:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Task 文件路径必须位于工作区内部：{path}")
