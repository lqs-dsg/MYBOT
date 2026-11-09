"""文件工具三件套：读 / 写 / 列目录

安全设计：所有路径都必须落在 workspace 内（防路径穿越），越界直接报错。
"""
from pathlib import Path
from typing import Optional

from mybot.agent.tools import Tool, ToolResult


class _WorkspaceBoundTool(Tool):
    """所有文件工具的公共基类：路径解析 + workspace 边界校验

    把 _resolve_in_workspace 提到基类，避免三个工具重复实现（改一处即全局生效）。
    """

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = Path(workspace).resolve() if workspace is not None else None

    def _resolve_in_workspace(self, path: str) -> Path:
        """把路径解析成绝对路径，并检查它是否在 workspace 内（防路径穿越）"""
        if self.workspace is None:
            raise ValueError("workspace 未配置，禁止文件操作")

        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        p = p.resolve(strict=False)          # 解析掉 ../ 和符号链接

        if not p.is_relative_to(self.workspace):
            raise ValueError(f"路径越界：{path} 不在 workspace 内")
        return p


# ==================== 读文件 ====================
class ReadFileTool(_WorkspaceBoundTool):
    name = "read_file"
    description = (
        "读取文件内容（带行号）。用途：查看文件内容、统计行数、确认文件是否存在。"
        "文件较大时可用 offset/limit 分页读取。"
        "⚠️ 查看/读取文件请用本工具，不要用 shell 的 type/cat/findstr 等命令。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对 workspace 或绝对路径）"},
            "offset": {"type": "integer", "description": "起始行号（从 0 开始，默认 0）"},
            "limit": {"type": "integer", "description": "最多读取行数（默认 200）"},
        },
        "required": ["path"],
    }

    async def execute(self, path: str, offset: int = 0, limit: int = 200) -> ToolResult:
        try:
            target = self._resolve_in_workspace(path)
        except ValueError as e:
            return ToolResult.error(str(e))

        if not target.exists():
            return ToolResult.error(
                f"文件不存在：{path}\n"
                f"提示：先用 list_files 查看目录里有哪些文件，找到正确路径后重试"
            )
        if target.is_dir():
            return ToolResult.error(
                f"路径是目录，不是文件：{path}\n"
                f"提示：用 list_files 查看该目录的内容"
            )

        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult.error(f"文件不是 UTF-8 文本，无法读取：{path}")
        except OSError as e:
            return ToolResult.error(f"读取文件失败：{e}")

        lines = text.splitlines()
        selected = lines[offset:offset + limit]

        output = "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(selected, start=offset))
        if offset + limit < len(lines):
            output += (f"\n\n[已截断] 仅展示第 {offset + 1}-{offset + len(selected)} 行，"
                       f"文件共 {len(lines)} 行。可增大 limit 或调整 offset 继续读")
        if not output:
            output = "（文件为空）"
        return ToolResult.ok(output)


# ==================== 写文件 ====================
class WriteFileTool(_WorkspaceBoundTool):
    name = "write_file"
    description = "写入文本文件。父目录不存在会自动创建；append=True 时追加而不是覆盖"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对 workspace 或绝对路径）"},
            "content": {"type": "string", "description": "要写入的文本内容"},
            "append": {"type": "boolean", "description": "True=追加，False=覆盖（默认 False）"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str, append: bool = False) -> ToolResult:
        try:
            target = self._resolve_in_workspace(path)
        except ValueError as e:
            return ToolResult.error(str(e))

        if target.is_dir():
            return ToolResult.error(f"路径是目录，不能写入：{path}")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a" if append else "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolResult.error(f"写入文件失败：{e}")

        action = "追加到" if append else "写入"
        return ToolResult.ok(f"成功{action}文件：{path}（{len(content)} 个字符）")


# ==================== 列目录 ====================
class ListFilesTool(_WorkspaceBoundTool):
    name = "list_files"
    description = "列出目录内容（不递归），返回每个条目的类型（dir/file）和大小"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径（默认当前目录）"},
            "max_entries": {"type": "integer", "description": "最多展示多少条（默认 100）"},
        },
        "required": [],
    }

    async def execute(self, path: str = ".", max_entries: int = 100) -> ToolResult:
        try:
            target = self._resolve_in_workspace(path)
        except ValueError as e:
            return ToolResult.error(str(e))

        if not target.exists():
            return ToolResult.error(f"目录不存在：{path}")
        if not target.is_dir():
            return ToolResult.error(f"路径不是目录：{path}（想看文件内容请用 read_file）")

        try:
            entries = sorted(target.iterdir())
        except OSError as e:
            return ToolResult.error(f"读取目录失败：{e}")

        if not entries:
            return ToolResult.ok(f"（空目录）{path}")

        lines = []
        for entry in entries[:max_entries]:
            try:
                kind = "dir " if entry.is_dir() else "file"
                size = entry.stat().st_size if entry.is_file() else 0
                lines.append(f"{kind} {size:>10}  {entry.name}")
            except OSError:
                lines.append(f"err? {0:>10}  {entry.name}")

        out = "\n".join(lines)
        if len(entries) > max_entries:
            out += f"\n\n[已截断] 共 {len(entries)} 条，仅展示前 {max_entries} 条"
        return ToolResult.ok(out)
