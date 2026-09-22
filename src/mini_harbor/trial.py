"""单个 Trial 的生命周期编排。"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass
from pathlib import Path

from mini_harbor.agents import create_agent
from mini_harbor.environment import LocalWorkspaceEnvironment
from mini_harbor.models import (
    ExceptionInfo,
    TimingInfo,
    TrialConfig,
    TrialResult,
    utc_now,
)
from mini_harbor.serialization import append_json_line, write_json
from mini_harbor.task import Task
from mini_harbor.verifier import create_verifier


@dataclass(frozen=True, slots=True)
class TrialPaths:
    """集中管理 Trial 产物路径，避免业务代码散落字符串。"""

    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def lock(self) -> Path:
        return self.root / "lock.json"

    @property
    def result(self) -> Path:
        return self.root / "result.json"

    @property
    def log(self) -> Path:
        return self.root / "trial.log"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def agent_dir(self) -> Path:
        return self.root / "agent"

    @property
    def verifier_dir(self) -> Path:
        return self.root / "verifier"


class Trial:
    """运行一次 Task × Agent × Attempt。"""

    def __init__(self, config: TrialConfig) -> None:
        self.config = config
        self.paths = TrialPaths(config.trial_dir)
        self.task = Task.load(config.task_path)
        self.agent = create_agent(config.agent_name)
        self.verifier = create_verifier(self.task)
        self.environment = LocalWorkspaceEnvironment(
            workspace=self.paths.workspace,
            seed_dir=self.task.environment_dir,
        )
        self.result = TrialResult(
            task_name=self.task.name,
            trial_name=config.trial_name,
            agent_name=self.agent.name,
        )

    def _event(self, name: str, **details: object) -> None:
        append_json_line(
            self.paths.log,
            {"at": utc_now(), "event": name, **details},
        )

    def _record_exception(self, exc: BaseException) -> None:
        """只保留首个异常，因为它通常最接近根因。"""

        if self.result.exception_info is not None:
            self._event(
                "secondary_exception",
                exception_type=type(exc).__name__,
                message=str(exc),
            )
            return
        self.result.exception_info = ExceptionInfo(
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            exception_traceback="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        )

    def _write_static_files(self) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        write_json(self.paths.config, self.config.to_dict())
        write_json(
            self.paths.lock,
            {
                "task": {
                    "name": self.task.name,
                    "path": str(self.task.path),
                    "digest": self.config.task_digest,
                },
                "agent": {"name": self.agent.name},
                "attempt_index": self.config.attempt_index,
            },
        )

    async def run(self) -> TrialResult:
        self._write_static_files()
        self._event("trial_started")

        try:
            await self._prepare()
            await self._run_agent()
            # 即使 Agent 超时或报错，也继续评分最终状态。这能区分“过程异常”和
            # “最终任务是否完成”，与真实 Evaluation Harness 的思路一致。
            await self._run_verifier()
        except Exception as exc:
            self._record_exception(exc)
            self._event(
                "trial_failed",
                exception_type=type(exc).__name__,
                message=str(exc),
            )
        finally:
            try:
                await self.environment.stop(delete=not self.config.keep_workspace)
            except Exception as exc:
                self._record_exception(exc)
            self.result.finished_at = utc_now()
            write_json(self.paths.result, self.result.to_dict())
            self._event(
                "trial_finished",
                reward=self.result.reward,
                exception=(
                    self.result.exception_info.exception_type
                    if self.result.exception_info
                    else None
                ),
            )

        return self.result

    async def _prepare(self) -> None:
        self.result.environment_setup = TimingInfo(started_at=utc_now())
        await self.environment.start()
        self.result.environment_setup.finished_at = utc_now()

        self.result.agent_setup = TimingInfo(started_at=utc_now())
        await self.agent.setup(self.environment)
        self.result.agent_setup.finished_at = utc_now()
        self._event("environment_and_agent_ready")

    async def _run_agent(self) -> None:
        self.result.agent_execution = TimingInfo(started_at=utc_now())
        self._event("agent_started")
        try:
            self.result.agent_result = await asyncio.wait_for(
                self.agent.run(self.task.instruction, self.environment),
                timeout=self.task.agent_timeout_sec,
            )
            write_json(
                self.paths.agent_dir / "trajectory.json",
                self.result.agent_result.actions,
            )
        except Exception as exc:
            self._record_exception(exc)
            self._event(
                "agent_failed",
                exception_type=type(exc).__name__,
                message=str(exc),
            )
        finally:
            self.result.agent_execution.finished_at = utc_now()
            self._event("agent_finished")

    async def _run_verifier(self) -> None:
        self.result.verifier = TimingInfo(started_at=utc_now())
        self._event("verifier_started")
        try:
            self.result.verifier_result = await asyncio.wait_for(
                self.verifier.verify(
                    self.task,
                    self.environment,
                    self.paths.verifier_dir,
                ),
                timeout=self.task.verifier_timeout_sec,
            )
        finally:
            self.result.verifier.finished_at = utc_now()
            self._event("verifier_finished", reward=self.result.reward)
