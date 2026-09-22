# Step 3：write-greeting Demo 实验记录

## 实验目标

使用 `rule-based-file-agent` 跑通一个非 Oracle、非大模型的完整 Evaluation：

```text
CLI → JobConfig → Job lock → TrialQueue → Trial
    → LocalWorkspaceEnvironment → Agent → Verifier
    → TrialResult → JobResult
```

本实验使用本地目录模拟 Environment。它适合学习数据流和生命周期，但不是安全沙箱，不能运行不可信代码。

## 实验输入

- Task：`examples/tasks/write-greeting`
- 指令：向 `greeting.txt` 写入 `Hello from Mini Harbor!`
- Agent：`rule-based-file-agent`
- Verifier：独立检查 `greeting.txt` 是否存在且内容完全匹配
- Attempt 数：2
- 最大并发数：2
- 最大重试次数：1
- 保留工作区：是，便于检查最终状态

## 执行命令

在项目根目录执行：

```powershell
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
python -m mini_harbor run `
  --path '.\examples\tasks\write-greeting' `
  --agent rule-based-file-agent `
  --n-attempts 2 `
  --n-concurrent 2 `
  --max-retries 1 `
  --jobs-dir '.\jobs' `
  --keep-workspace
```

实际 Job 目录：

```text
jobs/2026-09-22__23-36-40-749232
```

## 实际过程

### 1. Job 确定化

用户配置首先写入 `config.json`。Job 随后把一个 Task 和两个 attempt 展开为两个确定的 Trial，并写入 `lock.json`：

```text
demo-write-greeting__attempt-1__56f309d
demo-write-greeting__attempt-2__16fc383
```

两者使用相同的 Task 摘要：

```text
c7c0221439179579b14659ea607e418a1a0cf13cae43cd951f2fa73355a32bcb
```

### 2. Trial 生命周期

两个 Trial 都记录了相同的阶段顺序：

```text
trial_started
→ environment_and_agent_ready
→ agent_started
→ agent_finished
→ verifier_started
→ verifier_finished
→ trial_finished
```

`n_concurrent=2` 表示最多允许两个 Trial 同时运行，不承诺短任务一定产生可观察的时间重叠。

### 3. Agent 执行

两个 Agent 轨迹都只有一次确定性文件写入：

```json
{
  "type": "file_write",
  "path": "greeting.txt",
  "content_length": 24
}
```

保留下来的两个工作区均包含：

```text
greeting.txt = Hello from Mini Harbor!
context.txt  = This file represents the task's initial environment state.
```

这证明 Environment 既装载了初始状态，也保存了 Agent 修改后的最终状态。

### 4. Verifier 评分

两个 Trial 的 Verifier 原始输出均为：

```text
PASS: greeting.txt 内容符合预期
```

对应的 `verifier/reward.json` 均为：

```json
{
  "reward": 1.0
}
```

### 5. 结果聚合

终端摘要：

```text
Trials: 2/2 | Exceptions: 0 | Mean: 1.000 | Success rate: 100.0%
```

Job 结果：

| 指标 | 实际值 |
|---|---:|
| 总 Trial 数 | 2 |
| 完成 Trial 数 | 2 |
| 异常 Trial 数 | 0 |
| 实际重试次数 | 0 |
| 平均奖励 | 1.0 |
| 成功率 | 100% |

`max_retries=1` 只是允许失败后最多重试一次。本实验没有异常，因此没有触发重试。

## 结论

本次实验成功闭环，且三层证据一致：

1. Agent 轨迹表明目标文件已被写入；
2. Verifier 原始输出和 reward 都表明最终状态正确；
3. 两个 TrialResult 无异常，JobResult 聚合为满分。

因此，这里的“实验成功”不是只看 Agent 是否结束，而是同时满足：执行完成、最终状态通过独立校验、Trial 结果无异常、Job 聚合成功。
