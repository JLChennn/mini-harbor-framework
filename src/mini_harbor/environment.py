"""Environment 抽象与本地工作区实现。"""

from __future__ import annotations

import asyncio
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ExecResult:
    return_code: int
    stdout: str
    stderr: str


class BaseEnvironment(ABC):
    """Agent 和 Verifier 使用的统一执行环境接口。"""

    @property
    @abstractmethod
    def workspace(self) -> Path:
        raise NotImplementedError

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self, *, delete: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    async def write_text(self, relative_path: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def read_text(self, relative_path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def is_file(self, relative_path: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def exec(
        self,
        *command: str,
        timeout_sec: float | None = None,
    ) -> ExecResult:
        raise NotImplementedError


class LocalWorkspaceEnvironment(BaseEnvironment):
    """使用普通本地目录模拟 Harbor Environment。

    该实现只用于学习：它能隔离工作目录和校验路径穿越，但不是安全沙箱，
    不能用于运行不可信命令。Docker/Podman 级隔离明确不在 Mini 版范围内。
    """

    def __init__(self, workspace: Path, seed_dir: Path | None = None) -> None:
        self._workspace = workspace.resolve()
        self._seed_dir = seed_dir.resolve() if seed_dir and seed_dir.exists() else None
        self._started = False

    @property
    def workspace(self) -> Path:
        return self._workspace

    async def start(self) -> None:
        if self._started:
            return
        self._workspace.mkdir(parents=True, exist_ok=True)
        if self._seed_dir is not None:
            shutil.copytree(self._seed_dir, self._workspace, dirs_exist_ok=True)
        self._started = True

    async def stop(self, *, delete: bool) -> None:
        if delete and self._workspace.exists():
            shutil.rmtree(self._workspace)
        self._started = False

    def resolve_path(self, relative_path: str) -> Path:
        """解析工作区路径并阻止绝对路径、.. 和符号链接逃逸。"""

        candidate = (self._workspace / relative_path).resolve()
        try:
            candidate.relative_to(self._workspace)
        except ValueError as exc:
            raise ValueError(f"路径越出 Environment 工作区：{relative_path}") from exc
        return candidate

    async def write_text(self, relative_path: str, content: str) -> None:
        target = self.resolve_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def read_text(self, relative_path: str) -> str:
        return self.resolve_path(relative_path).read_text(encoding="utf-8")

    async def is_file(self, relative_path: str) -> bool:
        return self.resolve_path(relative_path).is_file()

    async def exec(
        self,
        *command: str,
        timeout_sec: float | None = None,
    ) -> ExecResult:
        """在工作区执行可信命令；Mini Demo 本身不依赖此能力。"""

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_sec,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        return ExecResult(
            return_code=process.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

