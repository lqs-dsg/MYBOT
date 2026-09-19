import json
import os
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from mybot.session.manager import SessionManager, safe_filename


def test_session_all():
    # 创建临时目录，测试完毕自动销毁
    tmp_dir = Path(tempfile.mkdtemp())
    sm = SessionManager(root_dir=tmp_dir)
    session_key = "cli:test"

    # -------- 测试点1：append + load 正常读写消息 --------
    msg1 = {"role": "user", "content": "hello world"}
    msg2 = {"role": "assistant", "content": "hi there"}
    sm.append(session_key, msg1)
    sm.append(session_key, msg2)

    loaded = sm.load(session_key)
    assert len(loaded) == 2
    assert loaded[0]["content"] == "hello world"
    assert loaded[1]["content"] == "hi there"
    assert "timestamp" in loaded[0]  # 自动补上时间戳

    # -------- 测试点2：max_messages 截断历史 --------
    msg3 = {"role": "user", "content": "third message"}
    sm.append(session_key, msg3)
    short = sm.load(session_key, max_messages=2)
    assert len(short) == 2
    assert short[0]["content"] == "hi there"
    assert short[1]["content"] == "third message"

    # -------- 测试点3：不存在会话，load 返回 [] --------
    empty = sm.load("teligram:groupA")
    assert empty == []

    # -------- 测试点4：safe_filename 过滤非法字符 --------
    bad_key = 'a<b>c:d"e/f\\g|h?i*j'
    sanitized = safe_filename(bad_key)
    for ch in ("<", ">", ":", '"', "/", "\\", "|", "?", "*"):
        assert ch not in sanitized

    # -------- 测试点5：文件存在损坏JSON坏行，load跳过不抛异常 --------
    bad_file = sm._path(session_key)
    with open(bad_file, "a", encoding="utf-8") as f:
        f.write("this is not valid json !!!\n")  # 坏行
        f.write(json.dumps({"role":"user","content":"good line"}) + "\n")

    recovered = sm.load(session_key)
    # 坏行被跳过，有效消息保留
    assert any(x["content"] == "good line" for x in recovered)

    # -------- 测试点6：append自动生成ISO格式timestamp --------
    no_ts_msg = {"role":"user","content":"no ts input"}
    sm.append(session_key, no_ts_msg)
    last_msg = sm.load(session_key)[-1]
    ts_str = last_msg["timestamp"]
    # 验证是iso格式，能被datetime解析
    datetime.fromisoformat(ts_str)

    # -------- 测试点7：remove 删除会话文件 --------
    assert bad_file.exists()
    sm.remove(session_key)
    assert not bad_file.exists()

    #清理临时目录
    shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == "__main__":
    test_session_all()
    print("全部7个测试点执行通过")