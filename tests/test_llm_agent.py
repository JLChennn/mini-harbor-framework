from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_harbor.environment import LocalWorkspaceEnvironment
from mini_harbor.job import Job
from mini_harbor.llm_agent import ResponsesFileAgent
from mini_harbor.models import JobConfig


def tool_response(path="greeting.txt"):
    return {"id": "resp-test", "status": "completed", "output": [{
        "type": "function_call", "call_id": "call-test", "name": "write_file",
        "arguments": json.dumps({"path": path, "content": "Hello from Mini Harbor!\n"}),
    }]}


class LLMTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_job_and_tool_result_roundtrip(self):
        agent = ResponsesFileAgent("test-secret", "https://example.com/v1", "test-model")
        sent = []

        def request(inputs):
            sent.append(json.loads(json.dumps(inputs)))
            if len(sent) == 1:
                return tool_response()
            return {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done"}]}]}

        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            with patch("mini_harbor.job.create_agent", return_value=agent), patch("mini_harbor.trial.create_agent", return_value=agent), patch.object(agent, "_request", side_effect=request):
                job = await Job.create(JobConfig(task_paths=[ROOT / "examples/tasks/llm-write-greeting"], agent_name=agent.name, jobs_dir=Path(temp), keep_workspaces=True))
                result = await job.run()
            self.assertEqual(result.mean_reward, 1.0)
            self.assertEqual(result.n_errored_trials, 0)
            self.assertEqual(sent[1][-1]["type"], "function_call_output")
            self.assertEqual(sent[1][-1]["call_id"], "call-test")
            self.assertEqual(json.loads(sent[1][-1]["output"]), {"ok": True})
            self.assertEqual(result.trial_results[0].agent_result.actions[-1]["reason"], "final_response")

    async def test_path_escape_is_returned_as_tool_error(self):
        agent = ResponsesFileAgent("test-secret", "https://example.com/v1", "test-model")
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            env = LocalWorkspaceEnvironment(Path(temp) / "workspace")
            await env.start()
            with patch.object(agent, "_request", side_effect=[tool_response("../escape.txt"), {"output": [{"type": "message", "role": "assistant", "content": []}]}]):
                await agent.run("write", env)
            self.assertFalse((Path(temp) / "escape.txt").exists())
            self.assertIn("error", agent.result.actions[2]["output"])

    async def test_api_failure_after_write_preserves_partial_evidence(self):
        agent = ResponsesFileAgent("test-secret", "https://example.com/v1", "test-model")
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            with patch("mini_harbor.job.create_agent", return_value=agent), patch("mini_harbor.trial.create_agent", return_value=agent), patch.object(agent, "_request", side_effect=[tool_response(), RuntimeError("HTTP 503")]):
                job = await Job.create(JobConfig(task_paths=[ROOT / "examples/tasks/llm-write-greeting"], agent_name=agent.name, jobs_dir=Path(temp)))
                result = await job.run()
            self.assertEqual(result.mean_reward, 1.0)
            self.assertEqual(result.n_errored_trials, 1)
            trajectory = job.trial_configs[0].trial_dir / "agent/trajectory.json"
            self.assertIn("tool_call", trajectory.read_text(encoding="utf-8"))
            self.assertNotIn("test-secret", trajectory.read_text(encoding="utf-8"))
