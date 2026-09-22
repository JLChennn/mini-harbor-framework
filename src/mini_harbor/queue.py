"""Trial 调度、并发限制与重试。"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable

from mini_harbor.models import RetryConfig, TrialConfig, TrialResult
from mini_harbor.serialization import write_json
from mini_harbor.trial import Trial


class TrialQueue:
    """用 asyncio.Semaphore 控制同时运行的 Trial 数量。"""

    def __init__(self, n_concurrent: int, retry: RetryConfig) -> None:
        self._semaphore = asyncio.Semaphore(n_concurrent)
        self._retry = retry

    def _should_retry(self, exception_type: str) -> bool:
        if exception_type in self._retry.exclude_exceptions:
            return False
        if (
            self._retry.include_exceptions
            and exception_type not in self._retry.include_exceptions
        ):
            return False
        return True

    def _backoff(self, retry_index: int) -> float:
        delay = self._retry.min_wait_sec * (
            self._retry.wait_multiplier**retry_index
        )
        return min(delay, self._retry.max_wait_sec)

    async def _run_one(
        self,
        config: TrialConfig,
        trial_factory: Callable[[TrialConfig], Trial],
    ) -> TrialResult:
        async with self._semaphore:
            for retry_index in range(self._retry.max_retries + 1):
                trial = trial_factory(config)
                result = await trial.run()
                result.retry_count = retry_index
                # Trial 会先写 result.json；队列再补写 retry_count，保证磁盘证据
                # 与最终交给 Job 聚合的对象一致。
                write_json(config.trial_dir / "result.json", result.to_dict())

                if result.exception_info is None:
                    return result
                if not self._should_retry(result.exception_info.exception_type):
                    return result
                if retry_index == self._retry.max_retries:
                    return result

                # Retry 表示重新运行同一个确定 Trial，因此清理上一次目录，
                # 但只删除 config 中明确指定的 trial_dir。
                shutil.rmtree(config.trial_dir, ignore_errors=True)
                await asyncio.sleep(self._backoff(retry_index))

        raise RuntimeError("TrialQueue 未产生结果，这不应该发生。")

    async def run(
        self,
        configs: list[TrialConfig],
        trial_factory: Callable[[TrialConfig], Trial] = Trial,
    ) -> list[TrialResult]:
        """保持输入顺序返回结果，方便 lock 与 result 对照。"""

        coroutines = [self._run_one(config, trial_factory) for config in configs]
        return list(await asyncio.gather(*coroutines))
