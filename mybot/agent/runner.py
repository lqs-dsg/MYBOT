import asyncio
from typing import List, Dict
from mybot.agent.tools import ToolRegistry
from mybot.providers.base import LLMProvider


class AgentRunner:
    def __init__(self, provider: LLMProvider, tools: ToolRegistry, max_iterations: int = 5):
        self.provider = provider          # ← 全程只叫 provider
        self.tools = tools                # ← 全程只叫 tools
        self.max_iterations = max_iterations

    async def run(self, messages: List[Dict]) -> str:
        for _ in range(self.max_iterations):
            resp = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
            )
            if not resp.tool_calls:
                return resp.content       # 模型直接给答案 → 结束

            # 协议要求：带 tool_calls 的 assistant 消息要进历史
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": resp.tool_calls,
            })

            # 逐个执行工具，结果作为 tool 消息喂回
            for call in resp.tool_calls:
                fn = call["function"]
                result = await self.tools.execute(fn["name"], fn["arguments"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": str(result),
                })
            # ← 内层 for 结束，回到外层 for 开头，再问模型一轮

        return "达到最大迭代次数"        # ← 必须在 for 外面！
