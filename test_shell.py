import asyncio
from mybot.agent.tools.registry import ToolRegistry
from mybot.agent.tools.shell import ShellTool
async def demo_shell_tool():
    reg = ToolRegistry()
    reg.register(ShellTool())

    print("=== Test1: 正常命令 echo hello from shell ===")
    r = await reg.execute("shell", {"command": "echo hello from shell"})
    assert not r.is_error, "正常命令不应该返回错误"
    assert "hello from shell" in str(r), "输出必须包含 hello from shell"
    print(" Test1 passed\n")

    print("=== Test2: 失败命令 exit 3 ===")
    r2 = await reg.execute("shell", {"command": "exit 3"})
    assert r2.is_error is True, "exit 3 退出码非0，应当返回错误"
    assert "exit 3" in str(r2)
    print(" Test2 passed\n")

    print("=== Test3: 输出截断测试，生成超长输出 ===")
    # 生成远超2000字符输出
    long_cmd = "python -c \"print('A'*3000)\""
    r3 = await reg.execute("shell", {"command": long_cmd})
    assert not r3.is_error
    assert "...(truncated)" in str(r3)
    print(" Test3 passed\n")

    print("=== Test4: 超时测试（sleep 35，超过30s超时阈值）===")
    r4 = await reg.execute("shell", {"command": "ping -n 36 127.0.0.1 > nul"})
    assert r4.is_error is True
    assert "命令超时" in str(r4)
    print(" Test4 passed\n")

    print(" All demo cases done")


if __name__ == "__main__":
    asyncio.run(demo_shell_tool())