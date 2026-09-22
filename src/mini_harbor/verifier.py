"""Verifier 抽象与文件断言评分器。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from mini_harbor.environment import BaseEnvironment
from mini_harbor.models import VerifierResult
from mini_harbor.serialization import write_json
from mini_harbor.task import Task


class BaseVerifier(ABC):
    """独立于 Agent 的评分接口。"""

    @abstractmethod
    async def verify(
        self,
        task: Task,
        environment: BaseEnvironment,
        verifier_dir: Path,
    ) -> VerifierResult:
        raise NotImplementedError


class FileAssertionVerifier(BaseVerifier):
    """检查目标文件是否存在且内容完全匹配。"""

    async def verify(
        self,
        task: Task,
        environment: BaseEnvironment,
        verifier_dir: Path,
    ) -> VerifierResult:
        target = task.verifier.path
        expected = task.verifier.expected_content.rstrip("\n") + "\n"

        if not await environment.is_file(target):
            reward = 0.0
            message = f"FAIL: {target} 不存在"
        else:
            actual = await environment.read_text(target)
            reward = 1.0 if actual == expected else 0.0
            message = (
                f"PASS: {target} 内容符合预期"
                if reward == 1.0
                else f"FAIL: {target} 内容不符合预期"
            )

        verifier_dir.mkdir(parents=True, exist_ok=True)
        (verifier_dir / "test-stdout.txt").write_text(
            message + "\n",
            encoding="utf-8",
        )
        write_json(verifier_dir / "reward.json", {"reward": reward})
        return VerifierResult(rewards={"reward": reward})


def create_verifier(task: Task) -> BaseVerifier:
    """当前 Task loader 已确保只会出现 file verifier。"""

    return FileAssertionVerifier()

