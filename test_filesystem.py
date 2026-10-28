"""文件工具测试

两个关键注意点（你的原版就踩了这两个坑）：
1. 工具的 execute 是 async 方法 → 必须 await！
2. 断言内容要用 str(ret) / ret.text —— ToolResult 不是字符串，不能直接 "xx" in ret
"""
from pathlib import Path

import pytest

from mybot.agent.tools.filesystem import ListFilesTool, ReadFileTool, WriteFileTool


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """每个测试一个独立隔离的 workspace（pytest 内置 tmp_path，跑完自动清理）"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ==================== 1. read 正常 ====================
@pytest.mark.asyncio
async def test_read_normal_with_lineno(workspace: Path):
    (workspace / "test.txt").write_text("foo\nbar\nbaz", encoding="utf-8")
    ret = await ReadFileTool(workspace=workspace).execute(path="test.txt")

    assert ret.is_error is False
    text = str(ret)
    assert "1\tfoo" in text
    assert "2\tbar" in text
    assert "3\tbaz" in text


# ==================== 2. read 不存在 ====================
@pytest.mark.asyncio
async def test_read_not_exists(workspace: Path):
    ret = await ReadFileTool(workspace=workspace).execute(path="not_such_file.txt")

    assert ret.is_error is True
    assert "不存在" in str(ret)


# ==================== 3. read 分页 ====================
@pytest.mark.asyncio
async def test_read_pagination_offset_limit(workspace: Path):
    (workspace / "page.txt").write_text("row0\nrow1\nrow2\nrow3\nrow4", encoding="utf-8")
    ret = await ReadFileTool(workspace=workspace).execute(path="page.txt", offset=2, limit=2)

    assert ret.is_error is False
    text = str(ret)
    assert "3\trow2" in text        # offset 从 0 开始 → 第 3 行
    assert "4\trow3" in text
    assert "row0" not in text       # 前面被跳过
    assert "row4" not in text       # 后面超出 limit


# ==================== 4. write 正常 ====================
@pytest.mark.asyncio
async def test_write_normal_create_file(workspace: Path):
    ret = await WriteFileTool(workspace=workspace).execute(path="w.txt", content="hello test")

    assert ret.is_error is False
    target = workspace / "w.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello test"


# ==================== 5. write 自动创建父目录 ====================
@pytest.mark.asyncio
async def test_write_auto_create_parent_dirs(workspace: Path):
    ret = await WriteFileTool(workspace=workspace).execute(path="a/b/c.txt", content="deep path")

    assert ret.is_error is False
    target = workspace / "a" / "b" / "c.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "deep path"


# ==================== 6. write 追加模式 ====================
@pytest.mark.asyncio
async def test_write_append_mode(workspace: Path):
    (workspace / "append.txt").write_text("first line\n", encoding="utf-8")
    ret = await WriteFileTool(workspace=workspace).execute(
        path="append.txt", content="second line", append=True
    )

    assert ret.is_error is False
    assert (workspace / "append.txt").read_text(encoding="utf-8") == "first line\nsecond line"


# ==================== 7. list 正常 ====================
@pytest.mark.asyncio
async def test_list_dir_normal(workspace: Path):
    (workspace / "note.txt").write_text("", encoding="utf-8")
    (workspace / "subdir").mkdir()

    ret = await ListFilesTool(workspace=workspace).execute(path=".")

    assert ret.is_error is False
    text = str(ret)
    assert "note.txt" in text
    assert "subdir" in text
    assert "file" in text           # 类型标记
    assert "dir" in text


# ==================== 8. ★ 路径穿越：读 ====================
@pytest.mark.asyncio
async def test_path_traversal_block_read(workspace: Path):
    """越界读必须被拒绝（安全底线）"""
    ret = await ReadFileTool(workspace=workspace).execute(path="../x.txt")

    assert ret.is_error is True     # ← 你原来写成了 is FutureWarning
    assert "越界" in str(ret)


# ==================== 9. ★ 路径穿越：写 ====================
@pytest.mark.asyncio
async def test_path_traversal_block_write(workspace: Path):
    """写操作同样要拦住越界，且外面不能真的被写出来"""
    ret = await WriteFileTool(workspace=workspace).execute(path="../evil.txt", content="x")

    assert ret.is_error is True
    assert "越界" in str(ret)
    assert not (workspace.parent / "evil.txt").exists()
