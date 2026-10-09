"""AgentLoop 测试

测试策略：只假"外部世界"，其余组件全真
  真: MessageBus / SessionManager / ContextBuilder / AgentRunner / ToolRegistry
  假: FakeProvider（剧本模型）+ EchoTool（假工具）

每个测试用独立临时目录，跑完自动销毁——连跑两次结果必须一致。

★ 原则：每个测试的"输入"和"期望输出"必须不同，
   否则无法区分"实现正确"和"只是把输入回显出来"（假阳性测试）。
"""
import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from mybot.agent.context import ContextBuilder
from mybot.agent.loop import AgentLoop
from mybot.agent.runner import AgentRunner
from mybot.agent.tools import Tool, ToolRegistry, ToolResult
from mybot.bus import InboundMessage, MessageBus
from mybot.providers.base import LLMProvider, LLMResponse
from mybot.session.manager import SessionManager


# ==================== 假工具 ====================
class EchoTool(Tool):
    """回显工具（测试用，避免执行真实副作用）"""

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
    """按剧本吐回复的假模型，并记录每次被调用时看到的 messages"""

    def __init__(self, script: list[LLMResponse]):
        super().__init__()
        self.script = list(script)
        self.calls = 0
        self.seen: list[list[dict]] = []

    def get_default_model(self) -> str:
        return "fake-model"

    async def chat(self, messages, model=None, tools=None, tool_choice=None) -> LLMResponse:
        self.calls += 1
        self.seen.append(list(messages))          # 快照：模型这一刻看到的历史
        return self.script.pop(0)


# ==================== helpers ====================
def make_msg(content: str, chat_id: str = "default", sender_id: str = "tester") -> InboundMessage:
    """造一条入站消息（channel 固定 cli）"""
    return InboundMessage(
        channel="cli",
        sender_id=sender_id,
        chat_id=chat_id,
        content=content,
    )


def make_loop(tmp_dir: Path, script: list[LLMResponse]):
    """组装一个 loop，返回 (loop, bus, provider, session)

    session 放 tmp_dir/sessions，引导文件从 tmp_dir/ws 读 —— 镜像真实布局。
    """
    bus = MessageBus()
    session = SessionManager(root_dir=tmp_dir / "sessions")
    ctx_builder = ContextBuilder(workspace=tmp_dir / "ws")

    tool_reg = ToolRegistry()
    tool_reg.register(EchoTool())

    provider = FakeProvider(script=script)
    runner = AgentRunner(provider=provider, tools=tool_reg)

    loop = AgentLoop(bus=bus, session=session, builder=ctx_builder, runner=runner)
    return loop, bus, provider, session


# ==================== 1. 端到端 turn（走总线） ====================
@pytest.mark.asyncio
async def test_end_to_end_single_turn():
    """消息进总线 → agent 处理 → 回复出总线"""
    ws = Path(tempfile.mkdtemp())
    try:
        # ★ 输入("喂，在吗？") 与期望输出("我在…") 必须不同
        script = [LLMResponse(content="我在，有什么可以帮你？")]
        loop, bus, provider, session = make_loop(tmp_dir=ws, script=script)

        await bus.publish_inbound(make_msg(content="喂，在吗？"))

        task = asyncio.create_task(loop.start())
        try:
            out = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
            assert out.content == "我在，有什么可以帮你？"
            assert out.channel == "cli"              # 路由信息来自入站消息
            assert out.chat_id == "default"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 2. 本轮对话落盘 ====================
@pytest.mark.asyncio
async def test_turn_history():
    """user 和最终 assistant 回复都要落盘"""
    ws = Path(tempfile.mkdtemp())
    try:
        script = [LLMResponse(content="我是 mybot")]
        loop, bus, provider, session = make_loop(tmp_dir=ws, script=script)

        await loop.handle_message(make_msg(content="你是谁？"))

        history = session.load("cli:default")
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[0]["content"] == "你是谁？"
        assert history[1]["content"] == "我是 mybot"     # 最终回复也落盘了
        assert all("timestamp" in m for m in history)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 3. ★ 跨 turn 记忆 ====================
@pytest.mark.asyncio
async def test_cross_turn_memory():
    """第二个 turn 时，模型必须能看到第一个 turn 的对话"""
    ws = Path(tempfile.mkdtemp())
    try:
        script = [
            LLMResponse(content="记住了"),
            LLMResponse(content="蓝色"),
        ]
        loop, bus, provider, session = make_loop(tmp_dir=ws, script=script)

        await loop.handle_message(make_msg("我最喜欢的颜色是蓝色"))    # turn 1
        await loop.handle_message(make_msg("我最喜欢什么颜色？"))       # turn 2

        assert provider.calls == 2
        second_call = provider.seen[1]                    # ★ turn 2 模型看到的
        assert [m["role"] for m in second_call] == ["system", "user", "assistant", "user"]

        contents = [m.get("content") for m in second_call]
        assert "我最喜欢的颜色是蓝色" in contents             # 记得 turn 1 的用户输入
        assert "记住了" in contents                         # 记得 turn 1 自己的回复
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 4. 工具消息落盘 ====================
@pytest.mark.asyncio
async def test_tool_message_persist():
    """工具调用请求 + 工具结果都要落盘，且 tool_call_id 能配对"""
    ws = Path(tempfile.mkdtemp())
    try:
        script = [
            LLMResponse(tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"text": "hello"}'},
            }]),
            LLMResponse(content="执行完了"),
        ]
        loop, bus, provider, session = make_loop(tmp_dir=ws, script=script)

        out = await loop.handle_message(make_msg("帮我 echo 一下"))
        assert out.content == "执行完了"

        history = session.load("cli:default")
        assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant"]

        tool_msg = [m for m in history if m["role"] == "tool"][0]
        assert tool_msg["tool_call_id"] == "call_1"
        assert tool_msg["content"] == "echo: hello"

        tool_req = [m for m in history if m["role"] == "assistant" and "tool_calls" in m][0]
        assert tool_req["tool_calls"][0]["id"] == "call_1"     # 与 tool_call_id 配对
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 5. 会话隔离 ====================
@pytest.mark.asyncio
async def test_session_isolation():
    """不同 chat_id 的历史互不干扰"""
    ws = Path(tempfile.mkdtemp())
    try:
        script = [LLMResponse(content="A的回复"), LLMResponse(content="B的回复")]
        loop, bus, provider, session = make_loop(tmp_dir=ws, script=script)

        await loop.handle_message(make_msg(content="我是A", chat_id="aaa"))
        await loop.handle_message(make_msg(content="我是B", chat_id="bbb"))

        hist_a = session.load("cli:aaa")
        hist_b = session.load("cli:bbb")

        assert len(hist_a) == 2 and len(hist_b) == 2
        assert hist_a[0]["content"] == "我是A"
        assert hist_a[1]["content"] == "A的回复"
        assert hist_b[0]["content"] == "我是B"
        assert hist_b[1]["content"] == "B的回复"
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 6. 异常不拖垮常驻循环 ====================
@pytest.mark.asyncio
async def test_loop_survives_handler_error():
    """第一条消息处理失败后，第二条仍应正常回复（start 的 except 起作用）"""

    class ExplodingProvider(LLMProvider):
        """第一次调用必炸，之后正常"""

        def __init__(self):
            super().__init__()
            self.calls = 0

        def get_default_model(self) -> str:
            return "boom-model"

        async def chat(self, messages, model=None, tools=None, tool_choice=None) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("模型炸了")
            return LLMResponse(content="我没事")

    ws = Path(tempfile.mkdtemp())
    try:
        bus = MessageBus()
        session = SessionManager(root_dir=ws / "sessions")
        builder = ContextBuilder(workspace=ws / "ws")
        tool_reg = ToolRegistry()
        tool_reg.register(EchoTool())
        runner = AgentRunner(provider=ExplodingProvider(), tools=tool_reg)
        loop = AgentLoop(bus=bus, session=session, builder=builder, runner=runner)

        await bus.publish_inbound(make_msg("第一条（会被异常打断）"))
        await bus.publish_inbound(make_msg("第二条（应该正常回复）"))

        task = asyncio.create_task(loop.start())
        try:
            # 第一条不产出 outbound，所以等到的一定是第二条的回复
            out = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
            assert out.content == "我没事"          # ★ 循环还活着
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    finally:
        shutil.rmtree(ws, ignore_errors=True)
