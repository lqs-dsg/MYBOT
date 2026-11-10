import sys
sys.path.append(".")
import asyncio

# 修复导入语句！！
from mybot.agent.tools.registry import ToolRegistry
from mybot.agent.tools.base import Tool, ToolResult


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
            "required": ["text"]
        }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.ok(f"echo: {kwargs['text']}")


class BadTool(Tool):
    @property
    def name(self) -> str:
        return "bad"

    @property
    def description(self) -> str:
        return "总是失败（测试用）"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("boom")


async def run_case_1_normal_call(reg: ToolRegistry):
    """用例1：正常调用execute("echo",{"text":"hello"})"""
    r = await reg.execute("echo", {"text": "hello"})
    assert not r.is_error, f"expect success, got {r}"
    assert str(r) == "echo: hello", f"expect='echo: hello', actual={r}"


async def run_case_2_json_str_param(reg: ToolRegistry):
    """用例2：传入JSON字符串参数"""
    r = await reg.execute("echo", '{"text": "hi"}')
    assert not r.is_error, f"expect success, got {r}"
    assert str(r) == "echo: hi", f"expect='echo: hi', actual={r}"


async def run_case_3_unknown_tool(reg: ToolRegistry):
    """用例3：调用不存在工具nope，返回错误，不抛出异常"""
    r = await reg.execute("nope", {})
    assert r.is_error


async def run_case_4_tool_raise_exception(reg: ToolRegistry):
    """用例4：工具内部抛异常，registry捕获包装错误结果"""
    r = await reg.execute("bad", {})
    assert r.is_error
    assert "boom" in str(r)


async def run_case_5_registry_lookup(reg: ToolRegistry):
    """用例5：registry查表行为"""
    echo_inst = reg.get("echo")
    assert echo_inst is not None

    nope_inst = reg.get("nope")
    assert nope_inst is None

    assert "echo" in reg.tool_names
    assert "bad" in reg.tool_names


async def main():
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(BadTool())

    await run_case_1_normal_call(reg)
    await run_case_2_json_str_param(reg)
    await run_case_3_unknown_tool(reg)
    await run_case_4_tool_raise_exception(reg)
    await run_case_5_registry_lookup(reg)
    print("[ok] 全部5个验收用例通过")


if __name__ == "__main__":
    asyncio.run(main())