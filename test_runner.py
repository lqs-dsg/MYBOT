from typing import List, Dict, Any
import pytest

from mybot.agent.runner import AgentRunner
from mybot.agent.tools import ToolRegistry, Tool, ToolResult
from mybot.providers.base import LLMProvider, LLMResponse


# ==================== 假工具 ====================
class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "回显文本（测试用假工具）"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.ok(f"echo: {kwargs['text']}")


# ==================== 假模型 ====================
class FakeProvider(LLMProvider):
    def __init__(self, script: List[LLMResponse]):
        super().__init__()
        self.script = list(script)
        self.calls = 0
        self.seen: List[List[Dict[str, Any]]] = []

    def get_default_model(self) -> str:
        return "fake-model"

    async def chat(self, messages, model=None, tools=None, tool_choice=None) -> LLMResponse:
        self.calls += 1
        self.seen.append(list(messages))      # 快照：模型这一刻看到的历史
        return self.script.pop(0)


def make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    return reg


# ==================== 场景1：一次答完 ====================
@pytest.mark.asyncio
async def test_single_reply():
    provider = FakeProvider([LLMResponse(content="你好")])
    runner = AgentRunner(provider, tools=make_registry(), max_iterations=5)

    result = await runner.run([{"role": "user", "content": "hi"}])

    assert result == "你好"
    assert provider.calls == 1


# ==================== 场景2：先工具后答案 ====================
@pytest.mark.asyncio
async def test_tool_answer():
    provider = FakeProvider([
        LLMResponse(tool_calls=[{
            "id": "call_001",
            "type": "function",
            "function": {"name": "echo", "arguments": '{"text": "hello"}'},
        }]),
        LLMResponse(content="工具执行完了"),
    ])
    runner = AgentRunner(provider, tools=make_registry(), max_iterations=5)

    result = await runner.run([{"role": "user", "content": "echo hello"}])

    assert result == "工具执行完了"
    assert provider.calls == 2

    # ★ 核心断言：第2轮模型看到的历史里有 tool 消息（证明结果喂回了模型）
    second_round = provider.seen[1]
    tool_msgs = [m for m in second_round if m["role"] == "tool"]
    assert len(tool_msgs) == 1, f"第2轮应有1条tool消息，实际: {second_round}"
    assert tool_msgs[0]["content"] == "echo: hello"
    assert tool_msgs[0]["tool_call_id"] == "call_001"


# ==================== 场景3：保险丝 ====================
@pytest.mark.asyncio
async def test_max_iterations_fuse():
    fake_tool_call = {
        "id": "call_loop",
        "type": "function",
        "function": {"name": "echo", "arguments": '{"text": "loop"}'},
    }
    provider = FakeProvider([LLMResponse(tool_calls=[fake_tool_call]) for _ in range(10)])
    runner = AgentRunner(provider, tools=make_registry(), max_iterations=3)

    result = await runner.run([{"role": "user", "content": "loop test"}])

    assert result == "达到最大迭代次数"
    assert provider.calls == 3