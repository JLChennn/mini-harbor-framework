"""Job：确定化 Trial、调用队列并聚合结果。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from mini_harbor.agents import create_agent
from mini_harbor.models import JobConfig, JobResult, TrialConfig, TrialResult, utc_now
from mini_harbor.queue import TrialQueue
from mini_harbor.serialization import append_json_line, write_json
from mini_harbor.task import Task


def _safe_name(name: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in name)


class Job:
    """一次评测批次的控制器。"""

    def __init__(
        self,
        config: JobConfig,
        job_id: str,
        job_dir: Path,
        trial_configs: list[TrialConfig],
    ) -> None:
        self.config = config
        self.job_id = job_id
        self.job_dir = job_dir
        self.trial_configs = trial_configs
        self.queue = TrialQueue(config.n_concurrent, config.retry)

    @classmethod
    async def create(cls, config: JobConfig) -> "Job":
        config.validate()
        # Preflight：在任何 Trial 入队之前验证 Agent 和 Task。
        create_agent(config.agent_name)
        tasks = [Task.load(path) for path in config.task_paths]

        job_id = str(uuid4())
        timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M-%S-%f")
        job_dir = (config.jobs_dir / timestamp).resolve()

        trial_configs: list[TrialConfig] = []
        for attempt_index in range(config.n_attempts):
            for task in tasks:
                suffix = uuid4().hex[:7]
                trial_name = (
                    f"{_safe_name(task.name)}__attempt-{attempt_index + 1}__{suffix}"
                )
                trial_configs.append(
                    TrialConfig(
                        task_path=task.path,
                        task_name=task.name,
                        task_digest=task.digest(),
                        trial_name=trial_name,
                        agent_name=config.agent_name,
                        attempt_index=attempt_index,
                        trial_dir=job_dir / trial_name,
                        keep_workspace=config.keep_workspaces,
                    )
                )

        job = cls(config, job_id, job_dir, trial_configs)
        job._write_plan_files()
        return job

    def _write_plan_files(self) -> None:
        self.job_dir.mkdir(parents=True, exist_ok=False)
        write_json(self.job_dir / "config.json", self.config.to_dict())
        write_json(
            self.job_dir / "lock.json",
            {
                "job_id": self.job_id,
                "trials": [config.to_dict() for config in self.trial_configs],
            },
        )
        write_json(
            self.job_dir / "result.json",
            {
                "job_id": self.job_id,
                "status": "pending",
                "n_total_trials": len(self.trial_configs),
            },
        )

    def _event(self, name: str, **details: object) -> None:
        append_json_line(
            self.job_dir / "job.log",
            {"at": utc_now(), "event": name, **details},
        )

    async def run(self) -> JobResult:
        started_at = utc_now()
        self._event("job_started", n_total_trials=len(self.trial_configs))
        write_json(
            self.job_dir / "result.json",
            {
                "job_id": self.job_id,
                "status": "running",
                "started_at": started_at,
                "n_total_trials": len(self.trial_configs),
            },
        )

        trial_results = await self.queue.run(self.trial_configs)
        result = self._aggregate(trial_results, started_at)
        write_json(self.job_dir / "result.json", result.to_dict())
        self._event(
            "job_finished",
            mean_reward=result.mean_reward,
            n_errored_trials=result.n_errored_trials,
        )
        return result

    def _aggregate(
        self,
        trial_results: list[TrialResult],
        started_at: str,
    ) -> JobResult:
        # 缺失 reward 按 0 计入均值，避免异常 Trial 从分母中消失。
        rewards = [result.reward if result.reward is not None else 0.0 for result in trial_results]
        total = len(self.trial_configs)
        mean_reward = sum(rewards) / total if total else 0.0
        successes = sum(reward >= 1.0 for reward in rewards)
        return JobResult(
            job_id=self.job_id,
            n_total_trials=total,
            trial_results=trial_results,
            started_at=started_at,
            finished_at=utc_now(),
            n_completed_trials=len(trial_results),
            n_errored_trials=sum(
                result.exception_info is not None for result in trial_results
            ),
            n_retries=sum(result.retry_count for result in trial_results),
            mean_reward=mean_reward,
            success_rate=successes / total if total else 0.0,
        )

