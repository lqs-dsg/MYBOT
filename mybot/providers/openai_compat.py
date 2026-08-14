import asyncio
from typing import List,Optional,Dict,Any
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion,ChatCompletionMessageToolCall
from .base import LLMProvider,LLMResponse


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
        completion = await client.chat.completions.create(
            model=use_model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=self.generation.temperature,
            max_tokens=self.generation.max_tokens,

        )
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

