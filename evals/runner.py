"""执行器：在独立的临时 workspace 里跑一个用例，返回轨迹与评分结果

两种模式：
- deterministic（默认）：用剧本化的 ScriptedProvider —— 不联网、毫秒级、可进 CI
- live：用真实模型（工厂函数注入）—— 测模型真实的工具选择与任务完成能力
"""
import shutil
import tempfile
import time
from pathlib import Path

from mybot.agent.context import ContextBuilder
from mybot.agent.loop import AgentLoop
from mybot.agent.runner import AgentRunner
from mybot.agent.tools import ToolRegistry
from mybot.agent.tools.filesystem import ListFilesTool, ReadFileTool, WriteFileTool
from mybot.agent.tools.shell import ShellTool
from mybot.bus import InboundMessage, MessageBus
from mybot.providers.base import LLMProvider, LLMResponse
from mybot.session.manager import SessionManager

from .graders import Trajectory, grade
from .loader import Case
from .report import CaseResult

EVAL_CHAT_ID = "default"


# ==================== 剧本模型（deterministic 模式） ====================
class ScriptedProvider(LLMProvider):
    """按剧本依次返回 LLMResponse

    剧本用完却还被调用 → 抛异常。这能立刻暴露"模型多问了一轮"这类问题，
    也防止用例作者写少了剧本时静默拿到错误结果。
    """

    def __init__(self, script):
        super().__init__()
        self.script = list(script or [])

    def get_default_model(self) -> str:
        return "scripted"

    async def chat(self, messages, model=None, tools=None, tool_choice=None) -> LLMResponse:
        if not self.script:
            raise RuntimeError(
                "剧本已用完但模型又被调用了 —— 执行轮数超出预期，请检查用例的 script"
            )
        item = self.script.pop(0)
        return LLMResponse(**item)


# ==================== 记录器（两种模式通用） ====================
class RecordingProvider(LLMProvider):
    """代理任意 provider，记录调用次数与 token 用量"""

    def __init__(self, inner: LLMProvider):
        super().__init__()
        self.inner = inner
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def get_default_model(self) -> str:
        return self.inner.get_default_model()

    async def chat(self, messages, model=None, tools=None, tool_choice=None) -> LLMResponse:
        self.calls += 1
        resp = await self.inner.chat(messages, model=model, tools=tools, tool_choice=tool_choice)
        self.prompt_tokens += resp.prompt_tokens or 0
        self.completion_tokens += resp.completion_tokens or 0
        return resp


# ==================== 装配（与 CLI 相同的结构，但 workspace 是临时目录） ====================
def build_eval_loop(provider: LLMProvider, workspace: Path):
    bus = MessageBus()
    session = SessionManager(root_dir=workspace / "sessions")
    builder = ContextBuilder(workspace=workspace)

    tools = ToolRegistry()
    tools.register(ShellTool(workspace=workspace))
    tools.register(ReadFileTool(workspace=workspace))
    tools.register(WriteFileTool(workspace=workspace))
    tools.register(ListFilesTool(workspace=workspace))

    runner = AgentRunner(provider=provider, tools=tools, max_iterations=8)
    loop = AgentLoop(bus=bus, session=session, builder=builder, runner=runner)
    return loop, session


# ==================== 轨迹提取：session 本身就是观测层 ====================
def extract_trajectory(messages: list, final_answer: str, iterations: int) -> Trajectory:
    tool_calls = [
        tc
        for m in messages
        if m.get("role") == "assistant"
        for tc in (m.get("tool_calls") or [])
    ]
    tool_error_count = sum(
        1 for m in messages if m.get("role") == "tool" and m.get("_is_error")
    )
    return Trajectory(
        final_answer=final_answer,
        messages=messages,
        tool_calls=tool_calls,
        iterations=iterations,
        tool_error_count=tool_error_count,
    )


# ==================== 跑一个用例 ====================
async def run_case(case: Case, live_provider_factory=None) -> CaseResult:
    """跑一个用例，返回带指标的 CaseResult

    live_provider_factory: 传 callable 则用真实模型跑 live 模式；None → deterministic
    """
    t0 = time.perf_counter()
    ws = Path(tempfile.mkdtemp(prefix="eval_"))
    try:
        # ① 准备沙箱文件
        for rel, content in (case.setup_files or {}).items():
            p = ws / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        # ② 选 provider（外面包一层记录器）
        inner = live_provider_factory() if live_provider_factory else ScriptedProvider(case.script)
        provider = RecordingProvider(inner)

        # ③ 装配并执行一个 turn
        loop, session = build_eval_loop(provider, ws)
        msg = InboundMessage(channel="cli", sender_id="eval", chat_id=EVAL_CHAT_ID,
                             content=case.input)
        out = await loop.handle_message(msg)

        # ④ 从 session 提取轨迹（复用持久化层作为观测层）
        messages = session.load(f"cli:{EVAL_CHAT_ID}")
        traj = extract_trajectory(messages, out.content or "", provider.calls)

        # ⑤ 评分
        ok, reason = grade(case, traj)
        latency_ms = (time.perf_counter() - t0) * 1000

        return CaseResult(
            case_id=case.id,
            category=case.category,
            passed=ok,
            reason=reason,
            iterations=provider.calls,
            tool_calls=len(traj.tool_calls),
            tool_errors=traj.tool_error_count,
            latency_ms=round(latency_ms, 1),
            prompt_tokens=provider.prompt_tokens,
            completion_tokens=provider.completion_tokens,
            tool_call_names=[c["function"]["name"] for c in traj.tool_calls],
        )
    finally:
        shutil.rmtree(ws, ignore_errors=True)
