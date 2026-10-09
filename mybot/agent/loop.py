import logging

from mybot.bus import MessageBus, InboundMessage, OutboundMessage
from mybot.session.manager import SessionManager
from mybot.agent.context import ContextBuilder
from mybot.agent.runner import AgentRunner

logger = logging.getLogger(__name__)


class AgentLoop:
    def __init__(self, bus: MessageBus, session: SessionManager,
                 builder: ContextBuilder, runner: AgentRunner):
        """所有依赖外部注入，不实例化任何内部组件"""
        self.bus = bus
        self.session = session
        self.builder = builder
        self.runner = runner

    async def handle_message(self, msg: InboundMessage) -> OutboundMessage:
        """一个完整 turn：读历史 → 组装上下文 → 跑循环 → 落盘 → 回信"""
        session_key = msg.session_key

        # ① 加载会话历史
        history = self.session.load(session_key)

        # ② 组装 LLM 上下文（★ build 是同步函数，不能 await）
        llm_context = self.builder.build(history, msg.content)

        # ③ 记住起点（runner 会原地追加）
        before = len(llm_context)

        # ④ 跑 agent 主循环（返回最终文本 str）
        reply = await self.runner.run(llm_context)

        # ⑤ 只追加"本轮新增"：user + 工具相关消息 + 最终回复
        new_messages = [
            {"role": "user", "content": msg.content},
            *llm_context[before:],
            {"role": "assistant", "content": reply},
        ]
        self.session.append_many(session_key, new_messages)   # ★ append_many

        # ⑥ 组装回信（路由信息来自入站消息）
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=reply,
        )

    async def start(self) -> None:
        """常驻消费循环：单条消息处理失败不能拖垮整个 agent"""
        while True:
            msg = await self.bus.consume_inbound()
            try:
                out = await self.handle_message(msg)
                await self.bus.publish_outbound(out)
            except Exception:
                logger.exception("处理消息失败: session_key=%s", msg.session_key)