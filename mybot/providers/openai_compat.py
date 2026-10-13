import asyncio
from typing import List,Optional,Dict,Any
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion,ChatCompletionMessageToolCall
from .base import LLMProvider,LLMResponse


# 只允许 API 认识的字段通过（剥掉我们本地的元数据，如 session 里的 timestamp）
_API_MESSAGE_KEYS = {"role", "content", "name", "tool_calls", "tool_call_id"}


def _to_api_messages(messages: List[dict]) -> List[dict]:
    """内部消息 → API 消息：白名单过滤，丢掉 timestamp 等本地字段

    背景：session 落盘时会给每条消息加 timestamp；从 JSONL 回放出来的历史
    会带着这个字段。若原样发给 API，未知字段可能导致 400 错误（第二轮对话必崩）。
    """
    return [{k: v for k, v in m.items() if k in _API_MESSAGE_KEYS} for m in messages]


class OpenAICompatProvider(LLMProvider):
    def __init__(self,api_key: Optional[str] = None, api_base: Optional[str] = None, default_model: str = "gpt-4o"):
        super().__init__(api_key,api_base)
        self.default_model=default_model
        self._client: AsyncOpenAI | None = None
        self._client_lock = asyncio.Lock()

    async def _ensure_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            self._client = AsyncOpenAI(
                api_key=self.api_key or "no-key",
                base_url=self.api_base,
            )
            return self._client
    def get_default_model(self) -> str:
        return self.default_model
    async def chat(self,messages:List[dict],model:Optional[str]=None, tools: Optional[list] = None, tool_choice: Optional[dict] = None)->LLMResponse:
        use_model =model or self.get_default_model()

        client = await self._ensure_client()

        # 组装请求参数：没有值的字段"不传"，而不是传 None
        # （显式传 None 会在 JSON body 里变成 null，部分兼容实现会报 400）
        kwargs: Dict[str, Any] = {
            "model": use_model,
            "messages": _to_api_messages(messages),   # ★ 清洗：挡掉 timestamp 等本地字段
            "temperature": self.generation.temperature,
            "max_tokens": self.generation.max_tokens,
        }
        if tools:                                     # ★ 有才传
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        completion = await client.chat.completions.create(**kwargs)
        return self._convert_response(completion)
    def _convert_response(self,completion:ChatCompletion)->LLMResponse:
        choice =completion.choices[0]
        msg =choice.message

        tool_calls_out:List[Dict[str,Any]]=[]
        if msg.tool_calls:
            tc:ChatCompletionMessageToolCall
            for tc in msg.tool_calls:
                tool_calls_out.append({
                    "id":tc.id,
                    "type":tc.type,
                    "function":{
                        "name":tc.function.name,
                        "arguments":tc.function.arguments
                    }
                })
        prompt_tokens =0
        completion_tokens=0
        if completion.usage:
            prompt_tokens=completion.usage.prompt_tokens
            completion_tokens =completion.usage.completion_tokens
        return LLMResponse(
            content=msg.content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=choice.finish_reason,
            tool_calls=tool_calls_out
        )

