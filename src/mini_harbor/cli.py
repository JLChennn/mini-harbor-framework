"""Mini Harbor 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Sequence

from mini_harbor.job import Job
from mini_harbor.models import JobConfig, RetryConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mini-harbor")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="运行一个本地评测 Job")
    run.add_argument("--path", action="append", required=True, type=Path)
    run.add_argument("--agent", default="rule-based-file-agent")
    run.add_argument("--n-attempts", type=int, default=1)
    run.add_argument("--n-concurrent", type=int, default=1)
    run.add_argument("--max-retries", type=int, default=0)
    run.add_argument("--jobs-dir", type=Path, default=Path("jobs"))
    run.add_argument("--keep-workspace", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    config = JobConfig(
        task_paths=args.path,
        agent_name=args.agent,
        n_attempts=args.n_attempts,
        n_concurrent=args.n_concurrent,
        jobs_dir=args.jobs_dir,
        keep_workspaces=args.keep_workspace,
        retry=RetryConfig(max_retries=args.max_retries),
    )
    job = await Job.create(config)
    result = await job.run()

    print(f"Job: {job.job_dir}")
    print(
        f"Trials: {result.n_completed_trials}/{result.n_total_trials} | "
        f"Exceptions: {result.n_errored_trials} | "
        f"Mean: {result.mean_reward:.3f} | "
        f"Success rate: {result.success_rate:.1%}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return asyncio.run(_run(args))
    raise AssertionError(f"未处理的命令：{args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

