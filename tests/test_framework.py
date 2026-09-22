from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


# 直接从 src 运行测试，不要求先执行 pip install。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mini_harbor.environment import LocalWorkspaceEnvironment
from mini_harbor.job import Job
from mini_harbor.models import (
    ExceptionInfo,
    JobConfig,
    RetryConfig,
    TrialConfig,
    TrialResult,
)
from mini_harbor.queue import TrialQueue


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def create_task(
    root: Path,
    instruction: str = "WRITE_FILE answer.txt\nmini-harbor-ok",
) -> Path:
    """创建仅服务于测试的临时 Task，不属于 Step 3 正式 Demo。"""

    task_dir = root / "task"
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")
    (task_dir / "environment" / "seed.txt").write_text("seed", encoding="utf-8")
    (task_dir / "task.toml").write_text(
        """[task]
name = "local/file-smoke"

[agent]
timeout_sec = 2

[verifier]
type = "file"
path = "answer.txt"
expected_content = "mini-harbor-ok"
timeout_sec = 2
""",
        encoding="utf-8",
    )
    return task_dir


class FrameworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_trial_writes_complete_evidence(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp:
            root = Path(temp)
            job = await Job.create(
                JobConfig(
                    task_paths=[create_task(root)],
                    jobs_dir=root / "jobs",
                )
            )

            result = await job.run()

            self.assertEqual(result.mean_reward, 1.0)
            self.assertEqual(result.success_rate, 1.0)
            self.assertEqual(len(result.trial_results), 1)
            trial = result.trial_results[0]
            self.assertEqual(trial.reward, 1.0)
            self.assertIsNone(trial.exception_info)

            trial_dir = job.trial_configs[0].trial_dir
            for path in (
                job.job_dir / "config.json",
                job.job_dir / "lock.json",
                job.job_dir / "result.json",
                trial_dir / "config.json",
                trial_dir / "lock.json",
                trial_dir / "result.json",
                trial_dir / "trial.log",
                trial_dir / "agent" / "trajectory.json",
                trial_dir / "verifier" / "reward.json",
                trial_dir / "verifier" / "test-stdout.txt",
            ):
                self.assertTrue(path.is_file(), path)

            # 默认清理执行现场，但保留配置、轨迹、评分和结果证据。
            self.assertFalse((trial_dir / "workspace").exists())
            reward = read_json(trial_dir / "verifier" / "reward.json")
            self.assertEqual(reward["reward"], 1.0)

    async def test_attempt_expansion_and_job_aggregation(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp:
            root = Path(temp)
            job = await Job.create(
                JobConfig(
                    task_paths=[create_task(root)],
                    jobs_dir=root / "jobs",
                    n_attempts=2,
                    n_concurrent=2,
                )
            )

            result = await job.run()

            lock = read_json(job.job_dir / "lock.json")
            self.assertEqual(len(lock["trials"]), 2)
            self.assertEqual(len(result.trial_results), 2)
            self.assertEqual(result.mean_reward, 1.0)
            self.assertEqual(result.success_rate, 1.0)

    async def test_agent_exception_is_recorded_and_verifier_still_runs(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp:
            root = Path(temp)
            job = await Job.create(
                JobConfig(
                    task_paths=[create_task(root, "UNSUPPORTED_ACTION")],
                    jobs_dir=root / "jobs",
                )
            )

            result = await job.run()

            trial = result.trial_results[0]
            trial_dir = job.trial_configs[0].trial_dir
            self.assertEqual(trial.reward, 0.0)
            self.assertIsNotNone(trial.exception_info)
            self.assertEqual(trial.exception_info.exception_type, "ValueError")
            verifier_reward = read_json(trial_dir / "verifier" / "reward.json")
            self.assertEqual(verifier_reward["reward"], 0.0)

    async def test_retry_policy_retries_a_matching_exception(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp:
            root = Path(temp)
            trial_dir = root / "trial"
            config = TrialConfig(
                task_path=create_task(root),
                task_name="local/file-smoke",
                task_digest="digest",
                trial_name="trial-1",
                agent_name="rule-based-file-agent",
                attempt_index=0,
                trial_dir=trial_dir,
            )
            calls = 0

            class FakeTrial:
                async def run(self) -> TrialResult:
                    nonlocal calls
                    calls += 1
                    exception = None
                    if calls == 1:
                        exception = ExceptionInfo(
                            exception_type="TransientError",
                            exception_message="try again",
                            exception_traceback="",
                        )
                    return TrialResult(
                        task_name=config.task_name,
                        trial_name=config.trial_name,
                        agent_name=config.agent_name,
                        exception_info=exception,
                    )

            queue = TrialQueue(
                n_concurrent=1,
                retry=RetryConfig(
                    max_retries=1,
                    min_wait_sec=0,
                    include_exceptions=["TransientError"],
                ),
            )

            results = await queue.run([config], trial_factory=lambda _: FakeTrial())

            self.assertEqual(calls, 2)
            self.assertEqual(results[0].retry_count, 1)
            persisted = read_json(trial_dir / "result.json")
            self.assertEqual(persisted["retry_count"], 1)

    async def test_local_environment_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp:
            root = Path(temp)
            environment = LocalWorkspaceEnvironment(root / "workspace")
            await environment.start()
            with self.assertRaises(ValueError):
                await environment.write_text("../escape.txt", "blocked")
            await environment.stop(delete=True)


if __name__ == "__main__":
    unittest.main()
