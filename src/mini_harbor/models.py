"""Mini Harbor 的配置、锁文件和结果数据模型。

完整 Harbor 使用 Pydantic 维护大量兼容性与校验逻辑。教学版只使用
标准库 dataclass，但仍然把“用户配置”“确定的 Trial”和“运行结果”分开。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    """返回便于 JSON 序列化的 UTC 时间。"""

    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RetryConfig:
    """Trial 失败后的最小重试策略。"""

    max_retries: int = 0
    min_wait_sec: float = 0.1
    wait_multiplier: float = 2.0
    max_wait_sec: float = 2.0
    include_exceptions: list[str] = field(default_factory=list)
    exclude_exceptions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class JobConfig:
    """用户希望运行的实验配置。"""

    task_paths: list[Path]
    agent_name: str = "rule-based-file-agent"
    n_attempts: int = 1
    n_concurrent: int = 1
    jobs_dir: Path = Path("jobs")
    keep_workspaces: bool = False
    retry: RetryConfig = field(default_factory=RetryConfig)

    def validate(self) -> None:
        if not self.task_paths:
            raise ValueError("Job 至少需要一个 Task。")
        if self.n_attempts < 1:
            raise ValueError("n_attempts 必须大于等于 1。")
        if self.n_concurrent < 1:
            raise ValueError("n_concurrent 必须大于等于 1。")
        if self.retry.max_retries < 0:
            raise ValueError("max_retries 不能为负数。")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["task_paths"] = [str(path) for path in self.task_paths]
        data["jobs_dir"] = str(self.jobs_dir)
        return data


@dataclass(slots=True)
class TrialConfig:
    """从 JobConfig 确定化得到的一次实验配置。"""

    task_path: Path
    task_name: str
    task_digest: str
    trial_name: str
    agent_name: str
    attempt_index: int
    trial_dir: Path
    keep_workspace: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["task_path"] = str(self.task_path)
        data["trial_dir"] = str(self.trial_dir)
        return data


@dataclass(slots=True)
class TimingInfo:
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(slots=True)
class ExceptionInfo:
    exception_type: str
    exception_message: str
    exception_traceback: str
    occurred_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class AgentResult:
    """教学版 Agent 轨迹摘要。"""

    actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class VerifierResult:
    rewards: dict[str, float]


@dataclass(slots=True)
class TrialResult:
    """一次 Task × Agent × Attempt 的完整结果。"""

    task_name: str
    trial_name: str
    agent_name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    retry_count: int = 0
    agent_result: AgentResult | None = None
    verifier_result: VerifierResult | None = None
    exception_info: ExceptionInfo | None = None
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    environment_setup: TimingInfo | None = None
    agent_setup: TimingInfo | None = None
    agent_execution: TimingInfo | None = None
    verifier: TimingInfo | None = None

    @property
    def reward(self) -> float | None:
        if self.verifier_result is None:
            return None
        return self.verifier_result.rewards.get("reward")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class JobResult:
    """一个 Job 对所有 TrialResult 的聚合结果。"""

    job_id: str
    n_total_trials: int
    trial_results: list[TrialResult]
    started_at: str
    finished_at: str
    n_completed_trials: int
    n_errored_trials: int
    n_retries: int
    mean_reward: float
    success_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
