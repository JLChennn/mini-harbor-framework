"""标准库实现的最小 Responses 工具循环；只允许工作区文件读写。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mini_harbor.agents import BaseAgent
from mini_harbor.environment import BaseEnvironment
from mini_harbor.models import AgentResult


def read_env(path: Path) -> dict[str, str]:
    """读取简单 KEY=VALUE 配置；不执行 shell，不修改全局环境变量。"""
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME", "OPENAI_API_MODE"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def file_tool(name: str, description: str, fields: tuple[str, ...]) -> dict:
    return {
        "type": "function", "name": name, "description": description,
        "parameters": {
            "type": "object",
            "properties": {field: {"type": "string"} for field in fields},
            "required": list(fields), "additionalProperties": False,
        },
        "strict": True,
    }


TOOLS = [
    file_tool("read_file", "Read a UTF-8 file at a workspace-relative path.", ("path",)),
    file_tool("write_file", "Write UTF-8 content at a workspace-relative path.", ("path", "content")),
]


class ResponsesFileAgent(BaseAgent):
    name = "responses-file-agent"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.result = AgentResult()

    @classmethod
    def from_env(cls) -> "ResponsesFileAgent":
        values = read_env(Path(".env"))
        if not values.get("OPENAI_API_KEY"):
            raise ValueError("请先在本地 .env 填入 OPENAI_API_KEY。")
        if values.get("OPENAI_API_MODE", "responses") != "responses":
            raise ValueError("responses-file-agent 仅支持 OPENAI_API_MODE=responses。")
        base_url = values.get("OPENAI_BASE_URL", "")
        if not base_url.startswith("https://"):
            raise ValueError("OPENAI_BASE_URL 必须是 HTTPS 地址。")
        model = values.get("MODEL_NAME", "")
        if not model:
            raise ValueError("MODEL_NAME 不能为空。")
        return cls(values["OPENAI_API_KEY"], base_url, model)

    def _redact(self, value: object) -> object:
        # 防止供应商错误响应或模型输出意外包含凭据。
        return json.loads(json.dumps(value, ensure_ascii=False).replace(self._api_key, "[REDACTED]"))

    def _request(self, inputs: list[dict]) -> dict:
        payload = {
            "model": self.model, "input": inputs, "tools": TOOLS,
            "stream": False, "store": False,
        }
        request = Request(
            self.base_url + "/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # 不落盘响应正文或 Authorization header。
            raise RuntimeError(f"Responses API HTTP {exc.code}") from None
        except URLError:
            raise RuntimeError("Responses API 网络连接失败（检查代理、DNS 和 TLS）。") from None
        if not isinstance(data, dict) or not isinstance(data.get("output"), list):
            raise RuntimeError("Responses API 返回了无效的 output。")
        return data

    async def run(self, instruction: str, environment: BaseEnvironment) -> AgentResult:
        self.result = AgentResult()
        inputs = [
            {"role": "system", "content": (
                "Complete the task by using file tools in the workspace. "
                "Use relative paths. After performing the task, give a brief final answer. "
                "You cannot access the verifier or its expected answer."
            )},
            {"role": "user", "content": instruction},
        ]
        self.result.actions.append({"type": "model_config", "model": self.model, "base_url": self.base_url, "api_mode": "responses", "max_turns": 4, "input": inputs.copy()})
        for turn in range(1, 5):
            response = await asyncio.to_thread(self._request, inputs)
            output = response["output"]
            self.result.actions.append(self._redact({
                "type": "model_response", "turn": turn, "id": response.get("id"),
                "model": response.get("model"), "status": response.get("status"),
                "usage": response.get("usage"), "output": output,
            }))
            if response.get("status") not in (None, "completed") or response.get("error"):
                raise RuntimeError("Responses API 未正常完成。")
            inputs.extend(output)
            calls = [item for item in output if item.get("type") == "function_call"]
            if not calls:
                if not any(item.get("type") == "message" for item in output):
                    raise RuntimeError("模型没有返回工具调用或最终消息。")
                self.result.actions.append({"type": "stop", "reason": "final_response", "turn": turn})
                return self.result
            for call in calls:
                try:
                    args = json.loads(call["arguments"])
                    if call["name"] == "read_file":
                        tool_output = {"content": await environment.read_text(args["path"])}
                    elif call["name"] == "write_file":
                        await environment.write_text(args["path"], args["content"])
                        tool_output = {"ok": True}
                    else:
                        raise ValueError("未知工具。")
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    tool_output = {"error": str(self._redact(str(exc)))}
                self.result.actions.append(self._redact({"type": "tool_call", "name": call["name"], "call_id": call["call_id"], "arguments": call["arguments"], "output": tool_output}))
                inputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(tool_output, ensure_ascii=False)})
        self.result.actions.append({"type": "stop", "reason": "max_turns"})
        raise RuntimeError("模型达到 4 轮上限，尚未返回最终消息。")
