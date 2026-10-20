# IQuest-Q1 真实模型最小冒烟测试

2026-10-07 11:22:47–11:22:50（Asia/Shanghai）运行成功。

## 验证目标

验证完整调用链：CLI → Job/lock → Trial → ResponsesFileAgent → IQuest-Q1 → 文件工具 → 独立 Verifier → TrialResult → JobResult。

本次实际调用供应商 API，没有使用规则 Agent 或 mock 替代模型。任务只要求创建一个固定内容的文本文件；它验证真实模型与评测框架的集成，不证明通用代码修复能力。

## 运行配置

- cwd：`C:\Users\CJL\Desktop\mini-harbor`
- 解释器：`C:\Users\CJL\AppData\Local\Programs\Python\Python313\python.exe`
- 模型请求名及供应商返回名：`IQuest-Q1`
- endpoint：`https://codeplan.iquestlab.com/api/predict/converge.converge/v1/responses`
- Agent：`responses-file-agent`
- Task：`examples/tasks/llm-write-greeting`
- Trial 数 1，并发 1，重试 0，保留 workspace；最大 4 轮，Task 超时 180 秒
- API key 从本地 `.env` 读取，不写入代码或运行产物

```powershell
$env:PYTHONPATH = "$PWD/src"
py -3.13 -X utf8 -m mini_harbor run --path examples/tasks/llm-write-greeting --agent responses-file-agent --n-attempts 1 --n-concurrent 1 --max-retries 0 --keep-workspace
```

## 真实轨迹与评分

| 轮次 | 模型行为 | Harness 执行结果 |
|---|---|---|
| 1 | 调用 write_file | 写入 `greeting.txt`，内容 `Hello from Mini Harbor!\n` |
| 2 | 调用 read_file | 返回刚写入的文件内容 |
| 3 | 返回最终消息 | stop reason 为 `final_response` |

3 次模型请求，2 次工具调用。供应商报告总 token 数相加为 1264（包含各轮历史输入，不代表独立文本量或账单金额）。

独立 Verifier 输出：`PASS: greeting.txt 内容符合预期`。

Job 聚合：1/1 Trial 完成，exception 为 null，reward 1.0，重试 0。该次运行的样本成功率为 100%，样本量只有 1。

本地证据目录（`jobs/` 被 Git 忽略）：

```text
jobs/2026-10-07__11-22-47-976153/
  config.json
  lock.json
  result.json
  smoke-llm-write-greeting__attempt-1__11e86d0/
    agent/trajectory.json
    verifier/reward.json
    verifier/test-stdout.txt
    result.json
    workspace/greeting.txt
```

## 离线回归与运行环境

`py -3.13 -X utf8 -m unittest discover -s tests -v`：8 项测试全部通过。其中 3 项新增测试使用 mock，分别验证工具回传与 Job 闭环、路径逃逸拦截、写入成功后 API 失败时保留轨迹并独立评分。

受限执行环境中的 TemporaryDirectory 发生 Windows 权限错误；上述通过的离线测试及真实冒烟测试在获准的沙箱外执行。未安装依赖。

## 面试表述

“我实现了一个最小 Agent Evaluation Harness，把 Task、Agent、Environment 和 Verifier 分离。接入 IQuest-Q1 后，模型通过 Responses 工具调用修改隔离工作目录，再由独立 Verifier 检查文件最终状态。一次真实冒烟测试跑了 3 轮模型请求、2 次工具调用，评分通过且没有过程异常；配置、轨迹和聚合结果都有本地证据。当前验证范围是文件任务，工作目录隔离不具备容器安全边界。”

Responses 工具调用格式参考 [OpenAI 官方 Function calling 文档](https://developers.openai.com/api/docs/guides/function-calling)。IQuest-Q1 的兼容性以本次真实运行证据为准。
