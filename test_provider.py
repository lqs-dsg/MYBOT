"""Provider 测试：验证"发出去的 HTTP 请求体"格式正确

技巧：用 httpx.MockTransport 替换真实网络 —— 既能断言请求内容，又不用联网、不花钱。
"""
import json

import httpx
import pytest
from openai import AsyncOpenAI

from mybot.providers.openai_compat import OpenAICompatProvider, _to_api_messages


def make_provider(captured: dict) -> OpenAICompatProvider:
    """造一个 provider，但把网络换成 MockTransport（请求体记录到 captured）"""

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    provider = OpenAICompatProvider(api_key="sk-test", api_base="https://example.com",
                                    default_model="m")
    # 关键：预置 _client，让 _ensure_client() 直接复用这个"假网络"客户端
    provider._client = AsyncOpenAI(
        api_key="sk-test", base_url="https://example.com",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return provider


# ==================== 1. 纯函数：字段白名单 ====================
def test_to_api_messages_strips_local_fields():
    """timestamp 等本地元数据必须被剥掉"""
    dirty = [{"role": "user", "content": "hi", "timestamp": "2026-01-01T00:00:00"}]
    assert _to_api_messages(dirty) == [{"role": "user", "content": "hi"}]


def test_to_api_messages_keeps_protocol_fields():
    """协议认识的字段必须保留（tool_calls / tool_call_id / name）"""
    msg = {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call_1"}], "timestamp": "x", "junk": 1,
    }
    out = _to_api_messages([msg])[0]
    assert out == {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]}


# ==================== 2. 真实请求体：不发本地字段、不发 null ====================
@pytest.mark.asyncio
async def test_chat_body_is_clean():
    """从 session 回放的消息（带 timestamp）+ 不传 tools/tool_choice 时，
    请求体里不应出现 timestamp、也不应出现 null 字段"""
    captured = {}
    provider = make_provider(captured)

    await provider.chat(
        messages=[{"role": "user", "content": "你好", "timestamp": "2026-01-01T00:00:00"}],
        tools=None,
        tool_choice=None,
    )

    body = captured["body"]
    assert "timestamp" not in body["messages"][0]     # 本地字段被挡住
    assert "tool_choice" not in body                  # 没值就不发，而不是发 null
    assert "tools" not in body
    assert body["model"] == "m"
    assert body["messages"][0]["content"] == "你好"


@pytest.mark.asyncio
async def test_chat_body_includes_tools_when_given():
    """传了 tools 就必须出现在请求体里（否则模型没法调用工具）"""
    captured = {}
    provider = make_provider(captured)
    tools = [{"type": "function",
              "function": {"name": "shell", "description": "d", "parameters": {}}}]

    await provider.chat(messages=[{"role": "user", "content": "hi"}], tools=tools)

    assert captured["body"]["tools"] == tools


# ==================== 3. 响应转换：API → LLMResponse ====================
@pytest.mark.asyncio
async def test_response_conversion():
    """工具调用和 token 用量要正确映射到 LLMResponse"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": None,
                                     "tool_calls": [{"id": "call_9", "type": "function",
                                                     "function": {"name": "shell",
                                                                  "arguments": '{"command":"dir"}'}}]},
                         "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        })

    provider = OpenAICompatProvider(api_key="k", api_base="https://example.com",
                                    default_model="m")
    provider._client = AsyncOpenAI(
        api_key="k", base_url="https://example.com",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content is None
    assert resp.prompt_tokens == 11
    assert resp.completion_tokens == 7
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0]["id"] == "call_9"
    assert resp.tool_calls[0]["function"]["name"] == "shell"
    assert resp.tool_calls[0]["function"]["arguments"] == '{"command":"dir"}'
