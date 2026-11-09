import asyncio
from pathlib import Path
from typing import Any
from .base import Tool,ToolResult

class ShellTool(Tool):
    name ="shell"
    description=(
        "执行系统命令（运行脚本、构建项目、查看系统信息、文件复制/移动等）。"
        "⚠️ 读取/写入/列出文件内容请优先使用 read_file / write_file / list_files 专用工具，"
        "本工具只用于真正需要执行命令的场景。"
        "注意：谨慎执行破坏性命令；单次执行最长30秒，输出会被截断"
    )
    parameters ={
        "type":"object",
        "properties": {
             "command":{"type":"string", "description": "要执行的shell命令"}

      },
        "required":["command"],
    }

    def __init__(self, workspace: Path | None = None):
        """workspace: 命令在哪个目录下执行（None = 继承当前进程的工作目录）

        绑定 workspace 的意义：agent 的操作被限制在它自己的地盘里，
        而不是跟着"你在哪里敲的命令"到处跑。
        """
        self.workspace = Path(workspace) if workspace is not None else None

    async def execute(self, command:str) -> ToolResult:

        if self.workspace is not None and not self.workspace.is_dir():
            return ToolResult.error(f"工作目录不存在: {self.workspace}")

        proc: asyncio.subprocess.Process | None = None
        try:
            proc =await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace) if self.workspace else None,   # ★ 在 workspace 里执行
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
             