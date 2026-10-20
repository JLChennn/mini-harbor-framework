"""Agent 抽象与确定性教学 Agent。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mini_harbor.environment import BaseEnvironment
from mini_harbor.models import AgentResult


class BaseAgent(ABC):
    """被 Harbor 评测的 Agent 统一接口。"""

    name: str

    async def setup(self, environment: BaseEnvironment) -> None:
        """真实 Agent 可在此安装 CLI、注入配置；教学 Agent 无需安装。"""

    @abstractmethod
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
    ) -> AgentResult:
        raise NotImplementedError


class RuleBasedFileAgent(BaseAgent):
    """理解一个极小指令协议的确定性 Agent。

    instruction.md 格式：

        WRITE_FILE answer.txt
        文件内容

    用途是测试 Evaluation Harness 链路。
    """

    name = "rule-based-file-agent"

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
    ) -> AgentResult:
        first_line, separator, content = instruction.partition("\n")
        command, command_separator, relative_path = first_line.partition(" ")
        if command != "WRITE_FILE" or not command_separator or not separator:
            raise ValueError(
                "RuleBasedFileAgent 只支持：WRITE_FILE <相对路径>\\n<内容>"
            )

        content = content.rstrip("\n") + "\n"
        await environment.write_text(relative_path.strip(), content)
        return AgentResult(
            actions=[
                {
                    "type": "file_write",
                    "path": relative_path.strip(),
                    "content_length": len(content),
                }
            ]
        )


def create_agent(name: str) -> BaseAgent:
    """最小 Agent Factory；后续可在此注册更多适配器。"""

    if name == RuleBasedFileAgent.name:
        return RuleBasedFileAgent()
    if name == "responses-file-agent":
        from mini_harbor.llm_agent import ResponsesFileAgent

        return ResponsesFileAgent.from_env()
    raise ValueError(f"未知 Agent：{name}")

