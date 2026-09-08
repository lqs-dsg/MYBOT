import asyncio
from typing import Any
from .base import Tool,ToolResult

class ShellTool(Tool):
    name ="shell"
    description=(
        "在本地系统执行shell等命令，用于查看文件，运行脚本，查询系统信息"
        "注意：谨慎执破坏性命令；单次执行最长30秒，输出会被截断"
    )
    parameters ={
        "type":"object",
        "properties": {
             "command":{"type":"string", "description": "要执行的shell命令"}

      },
        "required":["command"],
    }
    async def execute(self, **kwargs) -> ToolResult:
        command =kwargs["command"]
        proc: asyncio.subprocess.Process | None = None
        try:
            proc =await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout,stderr =await asyncio.wait_for(proc.communicate(),timeout=30)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception :
                pass
            return ToolResult.error("命令超时")
        stdout_text=stdout.decode("utf-8",errors="replace")
        stderr_text=stderr.decode("utf-8",errors="replace")
        max_len =2000
        if len(stdout_text) >max_len:
            stdout_text =stdout_text[:max_len] +"...(truncated)"
        if len(stderr_text)>max_len:
            stderr_text =stderr_text[:max_len] +"..(truncated)"
        returncode =proc.returncode
        if returncode != 0:
            err_payload = stderr_text if stderr_text else stdout_text
            return ToolResult.error(f"命令失败 (exit {returncode}): {err_payload}")

        output = stdout_text
        if stderr_text:
            output += f"\n[stderr]\n{stderr_text}"

        return ToolResult.ok(output)
             