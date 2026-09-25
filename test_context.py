"""ContextBuilder 测试

每个测试用独立的临时目录（不往项目里写垃圾），跑完自动销毁。
铁律：测试不能污染项目、不能互相影响——连跑两次结果必须一样。
"""
import shutil
import tempfile
from pathlib import Path

from mybot.agent.context import ContextBuilder


def make_ws() -> Path:
    """创建一个空的临时 workspace（落在系统临时目录，用完要销毁）"""
    return Path(tempfile.mkdtemp())


# ==================== 1. 消息顺序 ====================
def test_message_order():
    """第0条是 system，中间是历史，最后是本次 user 消息"""
    ws = make_ws()
    try:
        builder = ContextBuilder(workspace=ws, max_history_messages=10)
        history = [
            {"role": "user", "content": "历史问题1"},
            {"role": "assistant", "content": "历史回答1"},
        ]
        msgs = builder.build(history, "这是本次的用户消息")

        assert msgs[0]["role"] == "system"
        assert msgs[1]["content"] == "历史问题1"
        assert msgs[2]["content"] == "历史回答1"
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "这是本次的用户消息"
        assert len(msgs) == 4, f"应为 system+2条历史+user=4 条，实际 {len(msgs)}"
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 2. 引导文件被读取 ====================
def test_agents_md_loaded():
    """AGENTS.md 存在 → 内容进入 system prompt"""
    ws = make_ws()
    try:
        (ws / "AGENTS.md").write_text("总是用中文回答", encoding="utf-8")
        sys_text = ContextBuilder(workspace=ws).build_system_prompt()
        assert "总是用中文回答" in sys_text
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 3. 引导文件全缺失也不报错 ====================
def test_no_bootstrap_files_ok():
    """一个引导文件都没有 → 不报错，正常构建（优雅降级）"""
    ws = make_ws()
    try:
        builder = ContextBuilder(workspace=ws)
        sys_text = builder.build_system_prompt()
        assert "mybot" in sys_text                      # 基础提示词还在

        msgs = builder.build([], "你好")                 # 空历史也要能跑
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["content"] == "你好"
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 4. 引导文件优先级 ====================
def test_bootstrap_priority():
    """优先级顺序：AGENTS.md > SOUL.md > USER.md"""
    ws = make_ws()
    try:
        (ws / "AGENTS.md").write_text("项目指令A", encoding="utf-8")
        (ws / "SOUL.md").write_text("人格设定S", encoding="utf-8")
        (ws / "USER.md").write_text("用户画像U", encoding="utf-8")

        sys_text = ContextBuilder(workspace=ws).build_system_prompt()

        assert "项目指令A" in sys_text
        assert "人格设定S" in sys_text
        assert "用户画像U" in sys_text
        # 出现位置必须是 A → S → U
        assert sys_text.index("项目指令A") < sys_text.index("人格设定S") < sys_text.index("用户画像U")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 5. 历史截断 ====================
def test_history_truncated():
    """历史超上限 → 丢掉最老的，只保留最近 N 条"""
    ws = make_ws()
    try:
        builder = ContextBuilder(workspace=ws, max_history_messages=3)
        raw_history = [
            {"role": "user", "content": "h1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "h2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "h3"},
        ]
        msgs = builder.build(raw_history, "new msg")

        history_in_msg = msgs[1:-1]                     # 掐掉 system 和最后 user
        assert len(history_in_msg) == 3, f"应保留3条，实际 {len(history_in_msg)}"
        assert history_in_msg[0]["content"] == "h2"     # 最老的 h1/a1 被丢弃
        assert history_in_msg[-1]["content"] == "h3"
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 6. 不污染传入的 history ====================
def test_original_history_not_polluted():
    """build 不能修改调用方传进来的 history 列表"""
    ws = make_ws()
    try:
        builder = ContextBuilder(workspace=ws, max_history_messages=2)
        raw_history = [
            {"role": "user", "content": "old1"},
            {"role": "assistant", "content": "ans1"},
            {"role": "user", "content": "old2"},
        ]
        original_len = len(raw_history)
        builder.build(raw_history, "new")
        assert len(raw_history) == original_len
        assert raw_history[0]["content"] == "old1"      # 内容也没被动过
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ==================== 7. 中文往返 ====================
def test_chinese_roundtrip():
    """中文内容编码正常，读回来不变形"""
    ws = make_ws()
    try:
        builder = ContextBuilder(workspace=ws)
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，我是mybot"},
        ]
        msgs = builder.build(history, "帮你做测试")

        assert msgs[-1]["content"] == "帮你做测试"
        assert "你好，我是mybot" in [m["content"] for m in msgs]
    finally:
        shutil.rmtree(ws, ignore_errors=True)
