"""mybot 命令行入口

CLI 是最简单的 Channel：
    stdin 文本  →  InboundMessage(channel="cli", ...)  →  总线
    总线  →  OutboundMessage  →  stdout

两种模式：
    python -m mybot agent -m "你好"      # 一次性对话
    python -m mybot agent                # 交互模式（/exit 退出）
"""
import asyncio
from pathlib import Path
from typing import Optional

import typer

from mybot.agent.context import ContextBuilder
from mybot.agent.loop import AgentLoop
from mybot.agent.runner import AgentRunner
from mybot.agent.tools import ToolRegistry
from mybot.agent.tools.shell import ShellTool
from mybot.bus import InboundMessage, MessageBus
from mybot.config.loader import DEFAULT_CONFIG_PATH, load_config
from mybot.config.paths import get_workspace_path
from mybot.config.schema import Config
from mybot.providers.base import LLMProvider
from mybot.providers.openai_compat import OpenAICompatProvider
from mybot.session.manager import SessionManager

app = typer.Typer(help="mybot —— 个人 AI Agent")

# 单轮对话的等待上限（秒）：给模型多轮工具调用留足时间
TURN_TIMEOUT = 300


# ==================== 装配 ====================
def build_provider(config: Config) -> LLMProvider:
    """根据 config 造 provider（纯函数，无副作用，可单独测试）

    选择规则：
        agents.defaults.provider == "deepseek"  → 用 providers.deepseek
        否则                                     → 用 providers.openai
    模型优先级：
        agents.defaults.model  >  该 provider 的 model  >  "gpt-4o"
    """
    # 明确的 provider 名（"auto" 等一律落到 openai）
    provider_name = "deepseek" if config.agents.defaults.provider == "deepseek" else "openai"
    pc = getattr(config.providers, provider_name)

    model = config.agents.defaults.model or pc.model or "gpt-4o"

    if not pc.api_key:
        raise RuntimeError(
            f"未配置 API key。请在配置文件的 providers.{provider_name} 下填写 apiKey"
        )

    return OpenAICompatProvider(
        api_key=pc.api_key,
        api_base=pc.api_base,
        default_model=model,          # ★ 参数名是 default_model（不是 model）
    )


def build_loop(config: Config, workspace: Path) -> tuple[AgentLoop, MessageBus]:
    """装配整机：provider + tools + runner + session + builder + bus + loop"""
    bus = MessageBus()
    provider = build_provider(config)

    # 工具注册表
    tools = ToolRegistry()
    tools.register(ShellTool())                       # ★ ShellTool 无构造参数

    # 执行层 / 数据层 / 组装层
    runner = AgentRunner(provider=provider, tools=tools, max_iterations=8)
    session = SessionManager(root_dir=workspace / "sessions")   # ★ 参数名是 root_dir
    builder = ContextBuilder(workspace=workspace)

    # 协调层
    loop = AgentLoop(bus=bus, session=session, builder=builder, runner=runner)
    return loop, bus


# ==================== 消息转换 ====================
def make_inbound(text: str, chat_id: str = "default") -> InboundMessage:
    """stdin 文本 → InboundMessage"""
    return InboundMessage(
        channel="cli",            # ★ 必填
        sender_id="local",        # ★ 必填
        chat_id=chat_id,
        content=text,
    )


# ==================== 两种运行模式 ====================
async def run_once(loop: AgentLoop, bus: MessageBus, text: str,
                   chat_id: str = "default") -> str:
    """通过总线跑一个 turn（一次性对话）"""
    # ★ 必须先启动消费者，否则 consume_outbound 会永远等待（死锁）
    task = asyncio.create_task(loop.start())
    try:
        await bus.publish_inbound(make_inbound(text, chat_id))
        outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=TURN_TIMEOUT)
        return outbound.content
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def interactive(loop: AgentLoop, bus: MessageBus,
                      chat_id: str = "default") -> None:
    """交互模式：常驻 start()，循环 读输入 → 发总线 → 打印回复"""
    task = asyncio.create_task(loop.start())
    try:
        typer.echo("mybot 已就绪（输入 /exit 退出）")
        while True:
            # input() 是阻塞调用，必须丢到线程里，避免卡住事件循环
            text = (await asyncio.to_thread(input, "you> ")).strip()   # ★ strip 不是 split
            if text in ("/exit", "/quit"):
                break
            if not text:
                continue
            await bus.publish_inbound(make_inbound(text, chat_id))
            out = await bus.consume_outbound()
            typer.echo(f"mybot> {out.content}\n")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ==================== CLI 命令 ====================
@app.command()
def agent(
    message: str = typer.Option(None, "-m", "--message", help="发送一条消息后退出"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="配置文件路径"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", help="workspace 目录"),
    chat_id: str = typer.Option("default", "--chat-id", help="会话 ID（隔离不同会话）"),
):
    """与 agent 对话（不带 -m 进入交互模式）"""
    # ① 读配置（缺失时给人话，不是 traceback）
    try:
        cfg = load_config(config)
    except FileNotFoundError:
        typer.echo(
            f"错误：配置文件不存在 {config}\n\n"
            "请先创建它，内容示例：\n"
            "{\n"
            '  "providers": {\n'
            '    "deepseek": {\n'
            '      "apiKey": "sk-你的key",\n'
            '      "apiBase": "https://api.deepseek.com",\n'
            '      "model": "deepseek-chat"\n'
            "    }\n"
            "  },\n"
            '  "agents": { "defaults": { "provider": "deepseek" } }\n'
            "}",
            err=True,
        )
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"加载配置失败：{e}", err=True)
        raise typer.Exit(code=1)

    # ② 定 workspace（没传就用默认 ~/.mybot/workspace）
    if workspace is None:
        workspace = get_workspace_path()

    # ③ 装配
    try:
        agent_loop, bus = build_loop(cfg, workspace)
    except RuntimeError as e:
        typer.echo(f"初始化 Agent 失败：{e}", err=True)
        raise typer.Exit(code=1)

    # ④ 跑
    if message is not None:
        result = asyncio.run(run_once(agent_loop, bus, message, chat_id))
        typer.echo(result)
    else:
        asyncio.run(interactive(agent_loop, bus, chat_id))
