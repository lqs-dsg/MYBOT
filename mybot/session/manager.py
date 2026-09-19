import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime


_UNSAFE = {"<", ">", ":", '"', "/", "\\", "|", "?", "*"}


def safe_filename(session_key: str) -> str:
    name = session_key
    for char in _UNSAFE:
        name = name.replace(char, "_")
    return name


class SessionManager:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.root_dir.mkdir(exist_ok=True, parents=True)

    def _path(self, session_key: str) -> Path:
        fname = safe_filename(session_key)
        return self.root_dir / f"{fname}.jsonl"

    def load(self, session_key: str, max_messages: Optional[int] = None) -> List[dict]:
        file_path = self._path(session_key)
        if not file_path.exists():
            return []

        messages = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 坏行跳过

        if max_messages is not None and max_messages > 0:
            messages = messages[-max_messages:]
        return messages

    def append(self, session_key: str, msg: dict):
        file_path = self._path(session_key)
        if "timestamp" not in msg:
            msg["timestamp"] = datetime.now().isoformat()
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")


    def append_many(self, session_key: str, messages: list[dict]) -> None:
        """批量追加：一轮对话可能新增多条消息"""
        for msg in messages:
            self.append(session_key, msg)

    def remove(self, session_key: str):
        file_path = self._path(session_key)
        if file_path.exists():
            file_path.unlink()